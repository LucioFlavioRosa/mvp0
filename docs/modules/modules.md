# Módulo: modules (etapas de cadastro)

> Cada arquivo representa uma etapa do funil de cadastro do parceiro. Padrão consistente: classe com métodos `processar_<step>` que recebem texto do usuário e retornam `(novo_step, resposta)`.

## Propósito

Quebrar o fluxo de onboarding em pedaços pequenos e isolados. Cada etapa cuida de um conjunto coeso de inputs (ex: dados pessoais, endereço, documentos) e devolve qual o próximo estado da FSM. O `BotEngine` orquestra a transição entre etapas.

## Estrutura

| Arquivo | Classe | Etapa do funil |
|---|---|---|
| `onboarding.py` | `ModuloOnboarding` | Boas-vindas, decisão de continuar/refazer, check de device |
| `etapa_pessoal.py` | `EtapaPessoal` | CNPJ, CPF, nome, e-mail |
| `etapa_endereco.py` | `EtapaEndereco` | CEP, rua, bairro, número, distância máxima |
| `etapa_habilidades.py` | `EtapaHabilidades` | Quais serviços o parceiro realiza |
| `etapa_veiculos.py` | `EtapaVeiculos` | Carro, moto |
| `etapa_disponibilidade.py` | `EtapaDisponibilidade` | Agenda (semana, fim de semana, feriados) |
| `etapa_documentos.py` | `EtapaDocumentos` | CNH/RG, selfie, PIX, aceite de termos |
| `etapa_oferta.py` | `EtapaOferta` | Interceptação de oferta pendente (resposta a dispatch) |
| `common.py` | `GeradorResposta` | Helper estático para padronizar payloads de resposta |

## Contrato comum

Cada etapa segue o mesmo padrão (não é abstract class — convenção):

```python
class EtapaX:
    def iniciar_modulo(self, sender_id: str) -> tuple[str, dict]: ...
    def processar_<input>(self, texto: str, sender_id: str) -> tuple[str, dict]: ...
    # opcional, se a etapa suporta retomada após timeout:
    def reenviar_etapa_atual(self, step_backup: str) -> tuple[str, dict] | None: ...
```

Retorno é sempre `(novo_step, resposta_bot)`:

- `novo_step`: string com o nome do próximo estado da FSM (ex: `AGUARDANDO_CPF`).
- `resposta_bot`: dict com chave `tipo` — formato definido pelo padrão de mensagem (ver [`ARCHITECTURE.md → padrão de mensagem`](../ARCHITECTURE.md#padr%C3%A3o-de-mensagem)).

## `ModuloOnboarding`

Etapa de **entrada** do chat. Diferente das outras, não tem `processar_<campo>` — tem decisões binárias.

```python
class ModuloOnboarding:
    def processar_inicio(self, sender_id: str) -> tuple[str, dict]: ...
    def processar_decisao_refazer(self, texto: str, sender_id: str) -> tuple[str, dict]: ...
    def processar_decisao_continuar(self, texto: str, sender_id: str): ...   # retorna sinal ou (sinal, resp)
    def processar_check_device(self, texto: str, sender_id: str) -> tuple[str, dict]: ...
```

**Pontos não óbvios:**

- **`processar_decisao_continuar`** retorna **sinal especial** em vez de step, que o `BotEngine` interpreta na "Lógica Central de Retomada":
  - `'RETOMAR_FLUXO'` → BotEngine vai pra etapa salva no `step_backup`
  - `'DECISAO_REFAZER'` → oferece refazer
  - `'PAUSAR_FLUXO'` → mantém step anterior
- **Templates de WhatsApp**: o módulo referencia 3 templates registrados no portal Infobip (`TEMPLATE_CONTINUAR`, `TEMPLATE_REFAZER`, `TEMPLATE_CHECK`). Os identificadores ficam como `templateName` (string definida no portal). _Histórico:_ originalmente eram SIDs Twilio `HX...` durante a era pré-migração; foram convertidos em PR posterior.

## Etapas de campo (`EtapaPessoal`, `EtapaEndereco`, ...)

Padrão:

```python
class EtapaPessoal:
    def processar_cnpj(self, texto, sender_id): ...
    def processar_cpf(self, texto, sender_id): ...
    def processar_nome(self, texto, sender_id): ...
    def processar_email(self, texto, sender_id): ...
    def reenviar_etapa_atual(self, step_backup): ...
```

**Pontos não óbvios:**

- Validação acontece **dentro de cada `processar_<campo>`**: regex/limpeza + chamada de service. Em caso de input inválido, a etapa retorna o **mesmo step** com mensagem de erro — o `BotEngine` não salva (ver lógica em `_save_session`).
- Cada etapa pode chamar **múltiplos services** (ex: `EtapaEndereco.processar_cep` chama `ParceiroService.buscar_cidade_por_cep` + `salvar_cep_cidade`).
- **`reenviar_etapa_atual`** existe nas etapas que suportam retomada após timeout. Recebe o `step_backup` salvo na sessão e devolve a pergunta original (sem perder dados já preenchidos).

## `EtapaOferta`

Etapa **especial** — não faz parte do funil de cadastro, mas é checada **antes** dele em cada turno.

```python
class EtapaOferta:
    def verificar_oferta_pendente(self, sender_id: str) -> dict | None: ...
    def processar_resposta(self, texto: str, dados_oferta: dict, sender_id: str): ...
```

**Como é usado:**

- O `BotEngine.processar_mensagem` chama `verificar_oferta_pendente` **antes** de roteamento normal. Se retornar dict (existe oferta `ENVIADO` na `PEDIDOS_DISPAROS`), intercepta o fluxo e processa aceite/recusa.

**Pontos não óbvios:**

- **Prioridade**: oferta sobrescreve qualquer step ativo do cadastro. Se o user estava digitando CPF e cai uma oferta, a oferta vence.
- O step retornado por `processar_resposta` **não é salvo na sessão** — o BotEngine retorna `resposta` direto sem atualizar `CHAT_SESSIONS` no caminho de oferta.

## `GeradorResposta` (`common.py`)

```python
class GeradorResposta:
    @staticmethod
    def texto(msg: str, proximo_passo: str) -> tuple[str, dict]: ...
    @staticmethod
    def media(legenda: str, url_arquivo: str, proximo_passo: str) -> tuple[str, dict]: ...
    @staticmethod
    def template(sid: str, variaveis: dict, proximo_passo: str) -> tuple[str, dict]: ...
```

**Como é usado:**

- Helper estático pra evitar duplicação do dict de resposta em cada etapa.

**Pontos não óbvios:**

- **`template(sid, variaveis, ...)`** ainda usa o nome antigo (`sid` + `variaveis`). ⚠ Após migração Infobip, deveria ser `template_name` + `placeholders`. Não foi atualizado no PR de migração.
- **`media`** historicamente tinha docstring mencionando Twilio. Atualizar para Infobip no próximo touch nesse arquivo (cosmético).
- Esta classe é pouco usada na prática — a maioria das etapas constrói o dict inline. Considerar deprecar ou padronizar.

## O que NÃO está aqui

- **Orquestração entre etapas** → `app/bot_engine.py`
- **Persistência** → services (`ParceiroService`, `SessionService`)
- **Templates de WhatsApp** → cadastrados no portal Infobip (não no código)
