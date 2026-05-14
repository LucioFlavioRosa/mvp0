# Módulo: bot_engine

> Orquestrador central do chat. Máquina de estados que decide, a cada mensagem do parceiro, qual etapa do funil chamar e em qual estado salvar.

## Propósito

O `BotEngine` é o ponto único onde **todas as mensagens recebidas via WhatsApp são processadas**. Ele:

1. Carrega o estado atual da sessão do parceiro (banco).
2. Roteia a mensagem para a etapa correspondente (`EtapaPessoal`, `EtapaEndereco`, etc).
3. Salva o novo estado.
4. Retorna a resposta a enviar de volta.

Reside em arquivo único (`app/bot_engine.py`, 263 linhas) — não foi quebrado em sub-módulos intencionalmente, pois centralizar o switch facilita ver o fluxo completo.

## Estrutura

| Atributo | Tipo | Uso |
|---|---|---|
| `db` | `DatabaseManager` | Lê/grava `CHAT_SESSIONS` |
| `onboarding` | `ModuloOnboarding` | Entrada, decisões iniciais |
| `pessoal`, `endereco`, `habilidades`, `veiculos`, `disponibilidade`, `documentos`, `oferta` | Etapas | Lógica de campo |
| `MAPA_RETOMADA` | `dict[str, str]` | Mensagem de "retomando..." por step, usada após timeout |
| `SAUDACOES` | `list[str]` | Palavras que disparam menu inicial |

## API pública

```python
class BotEngine:
    def __init__(self) -> None: ...
    def processar_mensagem(
        self,
        sender_id: str,
        mensagem_texto: str,
        media_url: str | None = None,
    ) -> dict: ...
```

**Como é usado:**

- Chamado pelo `main.chat_webhook` para cada `result` no payload do Infobip.
- Retorna um dict `resposta_bot` (formato em [`ARCHITECTURE.md → padrão de mensagem`](../ARCHITECTURE.md#padr%C3%A3o-de-mensagem)).
- Erros são capturados e retornam `{'tipo': 'texto', 'conteudo': 'Erro interno...'}` — não levanta exceção.

**Métodos privados relevantes:**

- `_get_session(sender_id)` → `(step_atual, dados_dict, last_update)`. Aplica **timeout de 5 minutos** — se a última interação foi há mais de 300s, força `step = 'START'` e salva `step_backup` em `dados`. Retorna também o timestamp raw `LastUpdate` da linha — propagado pro `_save_session` para fechar o ciclo optimistic locking.
- `_save_session(sender_id, step, dados, last_update=None)` — `MERGE WITH (HOLDLOCK)` em `CHAT_SESSIONS` com **optimistic locking**: a cláusula `WHEN MATCHED AND target.LastUpdate = ?` só atualiza se ninguém alterou a linha desde o `_get_session` (detecta conflito via `rowcount=0`). `WITH (HOLDLOCK)` previne a race do UPSERT (dois workers ambos vendo "linha não existe" e tentando INSERT simultâneo). Pula steps transitórios (`START`, `NO_UPDATE`) pra não criar registros lixo.

## Fluxo

```mermaid
flowchart TD
    Start([Mensagem recebida]) --> CheckOferta{Oferta pendente<br>em PEDIDOS_DISPAROS?}
    CheckOferta -->|Sim| ProcOferta[EtapaOferta.processar_resposta]
    ProcOferta --> ReturnOferta([Resposta direta<br>sem atualizar sessão])

    CheckOferta -->|Não| LoadSession[_get_session]
    LoadSession --> CheckSaudacao{Texto é saudação<br>e step não é terminal?}
    CheckSaudacao -->|Sim| MenuInicio[onboarding.processar_inicio<br>salva step_backup]
    CheckSaudacao -->|Não| Roteamento{Switch por step_atual}

    Roteamento --> Pessoal[EtapaPessoal.*]
    Roteamento --> Endereco[EtapaEndereco.*]
    Roteamento --> Habilidades[EtapaHabilidades.*]
    Roteamento --> Veiculos[EtapaVeiculos.*]
    Roteamento --> Disponibilidade[EtapaDisponibilidade.*]
    Roteamento --> Documentos[EtapaDocumentos.*]
    Roteamento --> DecisaoContinuar[processar_decisao_continuar<br>→ lógica de retomada]

    DecisaoContinuar --> Retomada{Sinal retornado}
    Retomada -->|RETOMAR_FLUXO| MapaRetomada[Roteia pelo step_backup]
    Retomada -->|DECISAO_REFAZER| OfereceRefazer
    Retomada -->|PAUSAR_FLUXO| MantemStep

    Pessoal --> SaveSession[_save_session]
    Endereco --> SaveSession
    Habilidades --> SaveSession
    Veiculos --> SaveSession
    Disponibilidade --> SaveSession
    Documentos --> SaveSession
    MapaRetomada --> SaveSession

    SaveSession --> Return([Retorna resposta])
```

## Comportamentos não óbvios

### 1. Interceptação de oferta pendente (linhas 102–107)

Antes de qualquer outra coisa, o engine verifica se há oferta `ENVIADO` na `PEDIDOS_DISPAROS` para esse `WhatsAppID`. Se houver, **o cadastro é interrompido** e a resposta é tratada como aceite/recusa de oferta.

> **Por quê:** o parceiro pode estar no meio do cadastro e receber uma oferta urgente — precisa poder responder à oferta sem perder progresso no cadastro.

### 2. Timeout de sessão de 5 minutos (linhas 67–73)

Se passou mais de 300 segundos desde a última interação, o `step_atual` é forçado para `'START'` mas o **step real** é salvo em `dados['step_backup']`.

Isso permite que, no próximo turno, o `ModuloOnboarding` ofereça "continuar de onde parou" usando o `step_backup`.

### 3. Lógica central de retomada (linhas 138–200)

Quando o usuário responde "sim, continuar" após timeout, o engine **inspeciona o `step_backup`** e decide qual etapa retomar:

- Step contém `'VEICULO'` → `EtapaVeiculos`
- Step contém `'DISPONIBILIDADE'` → `EtapaDisponibilidade`
- Step contém `'HABILIDADE'` → `EtapaHabilidades`
- Step em `['AGUARDANDO_CNPJ', 'AGUARDANDO_CPF', 'AGUARDANDO_NOME', 'AGUARDANDO_EMAIL']` → `EtapaPessoal`
- Step relacionado a documentos → `EtapaDocumentos`
- **Fallback**: usa `MAPA_RETOMADA` (mensagem genérica de retomada por step)

> **Por quê:** evita o usuário ter que recomeçar do zero após uma pausa longa.

### 4. Saudações com backup

Se o usuário envia "oi"/"olá"/"menu" no meio de um cadastro, o engine **salva o step atual em `step_backup`** antes de mostrar o menu de novo. Permite voltar ao mesmo ponto se o user escolher "continuar".

### 5. Bloqueio de salvamento em steps transitórios

`_save_session` ignora se `step in ['START', 'NO_UPDATE']`. Sem isso, todo turno geraria um update no banco (mesmo quando nada mudou).

### 6. Optimistic locking contra webhooks concorrentes

Dois webhooks Infobip podem chegar quase simultâneos pro mesmo `WhatsAppID` (mensagens em sequência rápida) — sem locking, ambos lêem o mesmo estado, processam, e o segundo sobrescreve o trabalho do primeiro. O ciclo `_get_session → _save_session` resolve com:

```sql
MERGE CHAT_SESSIONS WITH (HOLDLOCK) AS target
USING (SELECT ? AS WhatsAppID) AS source
ON (target.WhatsAppID = source.WhatsAppID)
WHEN MATCHED AND target.LastUpdate = ? THEN   -- só atualiza se LastUpdate não mudou
    UPDATE SET CurrentStep = ?, TempData = ?, LastUpdate = GETDATE()
WHEN NOT MATCHED THEN                          -- HOLDLOCK serializa o predicate
    INSERT (WhatsAppID, CurrentStep, TempData, LastUpdate) VALUES (?, ?, ?, GETDATE());
```

- O segundo webhook detecta conflito (`rowcount=0` em `execute_write_with_rowcount`) e pode logar/abortar.
- `WITH (HOLDLOCK)` evita a race do UPSERT clássica: dois workers ambos vendo "não existe" e tentando INSERT simultâneo.

Detalhes do pattern em `docs/ARCHITECTURE.md` (decisão "Optimistic locking em CHAT_SESSIONS").

## O grande `if/elif`

Linhas 212–250 são um switch gigante por `step_atual`. **Não refatorar para FSM declarativa sem necessidade** — a ordem dos elifs codifica precedência (ex: `'DOCUMENTOS'` antes do fallback genérico), e o padrão `step.startswith('AGUARDANDO_X')` mistura match exato com prefixo. Reescrever isso pra FSM-table tem alto risco de bug sutil.

Se o switch crescer muito, considerar:

- **Tabela de dispatch**: `STEP_HANDLERS = {'AGUARDANDO_CNPJ': self.pessoal.processar_cnpj, ...}`.
- **Sub-roteadores por grupo** (já existe parcialmente — bot delega pra cada etapa).

## Erros conhecidos / fragilidades

- ~~**Sem logs estruturados** — `print` por todo lado~~ — **Resolvido**. Módulo usa `get_logger(__name__)` + custom dimensions canônicas (`OPERATION`, `SENDER_HASH` via `mask_pii`, `STEP`, etc), com `correlation_id` propagado pelo middleware. Filtragem no App Insights via Kusto fica direta.
- ~~**`traceback.print_exc()` em produção**~~ — **Resolvido**. Substituído por `logger.exception(...)` / `logger.error(..., exc_info=True)`.
- **`processar_inicio` é chamado tanto no caminho de erro quanto no normal** — duplicação de comportamento esperado/inesperado. Refatorar quando for tocar o roteamento.
- **Resposta genérica em caso de erro** (`"Ocorreu um erro interno"`) — não diferencia validação vs sistema. Trade-off vs UX: a Infobip não tem painel "essa mensagem foi 5xx", o usuário só vê o texto.
- **Optimistic locking só loga conflito** — em caso de `rowcount=0`, hoje o engine apenas loga e prossegue. Tornar visível em telemetria operacional (count de `optimistic_lock_conflict`) ajuda a entender frequência real do problema.

## Configurações

Tabelas SQL lidas/gravadas:

| Tabela | Operação |
|---|---|
| `CHAT_SESSIONS` | `SELECT` + `MERGE` (estado da máquina) |

Indiretamente, via etapas e services, toca `PARCEIROS_PERFIL`, `PEDIDOS_DISPAROS`, etc.

## O que NÃO está aqui

- **Validação de campo** → cada `EtapaX.processar_<campo>`
- **Envio de mensagens** → `WhatsAppService` ou `InfobipClient` (chamado por `main.chat_webhook`)
- **Persistência de dados do parceiro** → direto nas etapas (`etapa_pessoal.py`, `etapa_endereco.py`) via `DatabaseManager`
- **Templates de WhatsApp** → cadastrados no portal Infobip
