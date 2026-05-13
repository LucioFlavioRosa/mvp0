# Módulo: services

> Camada de aplicação entre o domínio (bot/modules) e o mundo externo (Infobip, Azure Blob, SQL).

## Propósito

Cada service encapsula uma capacidade externa ou um agregado de operações de domínio. O bot e os módulos de etapa nunca falam HTTP/SQL direto — sempre via service.

## Estrutura

| Arquivo | Classe principal | Responsabilidade |
|---|---|---|
| `whatsapp_service.py` | `WhatsAppService` | Envio outbound de mensagens via Infobip |
| `dispatch_service.py` | `DispatchService` | Notifica parceiros sobre novo pedido |
| `azure_blob_service.py` | `AzureBlobService` | Baixa mídia recebida no chat e sobe pro Blob |
| `session_service.py` | `SessionService` | Define estado de entrada do usuário (novo/em andamento/completo) |

> **Nota**: persistência do perfil do parceiro (CPF, nome, endereço, geo, etc) é feita **diretamente pelas etapas** (`app/modules/etapa_pessoal.py`, `etapa_endereco.py`) via `DatabaseManager`, sem camada de service intermediária. Houve um `ParceiroService` mas estava desconectado (dead code) — removido no PR `chore/remove-parceiro-service`.

## API pública por service

### `WhatsAppService`

```python
class WhatsAppService:
    def __init__(self) -> None: ...
    def enviar_resposta(self, to_number: str, resposta_bot: dict) -> None: ...
```

**Como é usado:**

- Chamado pelo `DispatchService` para disparar template a parceiros.
- O `main.py` envia mensagens diretamente via `InfobipClient` (não usa `WhatsAppService`) — duplicação histórica vinda do código pré-migração.

**Pontos não óbvios:**

- **Threading**: cada chamada de `enviar_resposta` dispara `threading.Thread` para não bloquear o caller. **Sem fila persistente** — se a app cai, mensagens em voo são perdidas.
- **Strip de prefixo**: aceita `to_number` com ou sem `whatsapp:` prefix — strip interno via `_strip_whatsapp_prefix`.
- **Padrão da mensagem (`resposta_bot`)**: dict com `tipo` (`texto`, `template`, `media`, `sequencia`, `combo_inicial`). Esse padrão é o contrato entre módulos do bot e este service — ver [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md#padr%C3%A3o-de-mensagem).
- **Retrocompatibilidade**: `_dict_to_positional_list` converte variáveis no estilo Twilio antigo (`{'1': 'a', '2': 'b'}`) para placeholders posicionais (`['a', 'b']`). Mantém callers não migrados funcionando. ⚠ Idealmente todos callers já passam `placeholders` direto.
- **Linguagem do template**: constante `DEFAULT_TEMPLATE_LANGUAGE = "pt_BR"`. Pra templates em outros idiomas, caller passa `language` no dict.

### `DispatchService`

```python
class DispatchService:
    def __init__(self) -> None: ...
    def enviar_oferta_para_prestadores(
        self,
        lista_uuids: list[str],
        pedido_uuid: str,
    ) -> dict: ...
```

**Como é usado:**

- Chamado pelo endpoint `POST /api/dispatch` quando um pedido novo entra no backoffice.
- Lê dados do pedido em `PEDIDOS_SERVICO`, busca cada parceiro em `PARCEIROS_PERFIL`, registra disparo em `PEDIDOS_DISPAROS`, e envia template via `WhatsAppService`.

**Pontos não óbvios:**

- **Template `oferta_servico`** com 9 placeholders posicionais: `[nome, atividade, numero, rua, bairro, data, observacao, valor, urgencia]`. ⚠ Re-cadastrar no portal Infobip com essa ordem antes de qualquer deploy.
- Retorna `{"status": "success", "enviados": <n>}` **mesmo se algum envio falhar** — falha individual vira log via `WhatsAppService`. Endpoint nunca propaga 5xx por falha de mensagem.
- **Sem retry**: se o INSERT em `PEDIDOS_DISPAROS` falha, o envio é pulado pra esse parceiro (sem aviso ao caller).

### `AzureBlobService`

```python
class AzureBlobService:
    def __init__(self) -> None: ...
    def upload_from_url(self, media_url: str, container_name: str, blob_name: str) -> str | None: ...
```

**Como é usado:**

- Chamado por `EtapaDocumentos` quando o parceiro envia foto (CNH, RG, selfie) via WhatsApp.
- Baixa do Infobip (URL privada com auth) e sobe pro Azure Blob (URL pública via container privado + SAS).

**Pontos não óbvios:**

- **Auth header**: `Authorization: App <INFOBIP-API-KEY>` para baixar mídia do Infobip. Diferente do Twilio antigo que usava Basic Auth.
- **⚠ URL pública vs privada**: dependendo da config do tenant Infobip, mídia inbound pode vir como URL pública (sem auth). Se receber 401/403 ao baixar, remover o header. Ver `MIGRATION_NOTES.md` item 5.
- **Container**: criado on-demand (`create_container` se não existe). Recomendável criar previamente com policy de acesso correta.
- **Retry transient no download**: `_download_midia` é decorado com `@transient_retry` — 2 tentativas em timeout/connection/5xx. 4xx (URL inválida, auth) loga WARNING e retorna `None` (não tenta de novo). Erro persistente retorna `None`.
- **DLQ pós-falha**: tanto em 4xx (`attempts=1`) quanto em erro persistente pós-retry (`attempts=2`), o `_enqueue_dlq` enfileira a tentativa em `outbound-dlq` (Azure Storage Queue). Operação `download_media`, payload com `media_url`/`container_name`/`blob_name`. Recuperável via `POST /admin/dlq/retry/{id}`.

### `SessionService`

```python
class SessionService:
    def __init__(self) -> None: ...
    def verificar_entrada_usuario(self, whatsapp_id: str) -> dict: ...
    def iniciar_nova_sessao(self, whatsapp_id: str) -> None: ...
    def arquivar_usuario_antigo(self, whatsapp_id: str) -> None: ...
```

**Como é usado:**

- Chamado por `ModuloOnboarding.processar_inicio` no primeiro turno do chat.
- `verificar_entrada_usuario` retorna `{'tipo': 'NOVO_USUARIO' | 'CADASTRO_ANDAMENTO' | 'CADASTRO_COMPLETO'}` baseado em sessão ativa + status do perfil.

**Pontos não óbvios:**

- **Regra de ouro**: se existe perfil com status diferente de `ATIVO`/`EM_ANALISE`, sempre trata como "em andamento" mesmo que a sessão esteja `FINALIZADO`. Permite retomada após user abandonar o chat.
- **Arquivamento**: `arquivar_usuario_antigo` muda o `WhatsAppID` do registro antigo pra `<id>_v<hash>`, liberando o número original pra novo cadastro. Não deleta — preserva histórico LGPD.

## Pontos de fragilidade compartilhados

Itens que afetam mais de um service e valeria endereçar:

- **Retry transient + DLQ implementados** em chamadas HTTP externas (Infobip, Blob download, ViaCEP, Google Maps) via `app/core/retry.py` (2 tentativas, backoff exponencial). Falhas pós-retry são **persistidas na DLQ** (Azure Storage Queue `outbound-dlq`, ver `app/integrations/dlq.py`) e recuperáveis manualmente via endpoints admin `GET /admin/dlq` e `POST /admin/dlq/retry/{message_id}` (autenticados com `ADMIN-USER`/`ADMIN-PASSWORD`). Política: 1 tentativa manual por mensagem, delete obrigatório no fim — evita fila poluída com mensagens fantasmas.
- **Mock de validação de CNPJ** ainda inline em `etapa_pessoal.processar_cnpj` (logger `validacao mock CNPJ`, regra fake "termina em 0000 é inválido"). ⚠ Bloqueador de prod — substituir por integração Serpro/Receita Federal. (ViaCEP e Google Maps já são chamadas reais em `etapa_endereco.py`.)
- **`time.sleep`** em vários lugares (`WhatsAppService._processar_sequencia`, `main.enviar_sequencia_background`) — segura a thread. Pra escala, considerar Service Bus + worker.

## O que NÃO está aqui

- **Lógica de chat / FSM** → `app/bot_engine.py`
- **Etapas individuais do onboarding** → `app/modules/etapa_*`
- **Schemas Pydantic** → `app/schemas/`
- **Cliente HTTP do Infobip** → `app/integrations/infobip.py`
