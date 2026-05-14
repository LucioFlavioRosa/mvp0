# Módulo: integrations + schemas

> Camada de saída/entrada para integrações externas: HTTP do Infobip e duas filas Azure Storage Queue (DLQ + sequências). Combina clientes (`integrations/`) e schemas Pydantic (`schemas/`).

## Propósito

Isola toda a comunicação com sistemas externos. Outro código (services, routers, main) usa esta camada — não fala HTTP nem queue direto. Trocar de provedor (Infobip → outro) ou de fila (Storage Queue → Service Bus) deveria afetar **só os arquivos desta pasta**.

## Estrutura

| Arquivo | Classe / Schema | Responsabilidade |
|---|---|---|
| `app/integrations/infobip.py` | `InfobipClient` | Envia requests autenticados pra API Infobip |
| `app/integrations/dlq.py` | `DLQClient` | Cliente Azure Storage Queue `outbound-dlq` — persiste falhas pós-retry para admin retry manual |
| `app/integrations/sequence_queue.py` | `SequenceQueueClient` | Cliente Azure Storage Queue `outbound-sequences` — enfileira sequências de mensagens consumidas pelo `sequence_worker` |
| `app/schemas/infobip_webhook.py` | `InfobipInboundPayload` + sub-schemas | Valida e tipa o payload JSON do webhook inbound |
| `app/schemas/dlq.py` | `DLQMessage` | Schema Pydantic do payload enfileirado na DLQ (operation, external_service, payload, attempts, sender_hash) |

## API pública

### `InfobipClient`

```python
class InfobipClient:
    def __init__(self, api_key: str, base_url: str, timeout: float = 10.0) -> None: ...
    def send_text(self, sender: str, to: str, text: str) -> dict[str, Any]: ...
    def send_image(self, sender: str, to: str, media_url: str, caption: str | None = None) -> dict[str, Any]: ...
    def send_template(self, sender: str, to: str, template_name: str, language: str, placeholders: list[str]) -> dict[str, Any]: ...
    def close(self) -> None: ...
```

**Como é usado:**

- Instanciado **uma vez no lifespan startup** (`main.py`) — apenas se `INFOBIP-API-KEY`, `INFOBIP-BASE-URL` e `INFOBIP-SENDER` estiverem presentes — e armazenado em `app.state.infobip_client`. Routers acessam via `Depends(get_infobip_client)` (que levanta 503 se for `None`).
- `WhatsAppService.__init__` também instancia um cliente próprio (uso interno do service); o `sequence_worker` instancia outro no boot da thread daemon.
- Re-usa uma `requests.Session` — connection pooling via HTTPS keep-alive.

**Pontos não óbvios:**

- **Auth**: header `Authorization: App <api_key>` — não é Basic Auth (diferente do Twilio antigo).
- **Números**: o `sender` e `to` são E164 sem prefixo `whatsapp:` nem `+` (ex: `5511999998888`). Strip de prefixo é responsabilidade do caller (`WhatsAppService._strip_whatsapp_prefix`).
- **`send_template`**: usa array `placeholders` (posicional), não dict por chave como o Twilio (`content_variables`). A ordem é a do template cadastrado no portal Infobip.
- **Erros 4xx/5xx**: `raise_for_status()` levanta `requests.HTTPException`. Caller decide se faz retry ou loga e segue.
- **Retry transient**: o método `_post` é decorado com `@transient_retry` (em `app/core/retry.py`) — 2 tentativas com backoff exponencial 1-5s, só em `requests.Timeout`, `requests.ConnectionError` ou HTTP 5xx. 4xx propaga direto (request inválida não melhora com retry). Falhas após retry levantam exceção pro caller decidir (geralmente log + drop).

### Schemas Pydantic

```python
class InfobipMessageText(BaseModel):
    type: Literal["TEXT"]
    text: str

class InfobipMessageImage(BaseModel):
    type: Literal["IMAGE"]
    url: str
    caption: str | None

class InfobipResult(BaseModel):
    sender: str = Field(alias="from")     # "from" é palavra reservada em Python
    to: str
    message_id: str = Field(alias="messageId")
    received_at: datetime = Field(alias="receivedAt")
    message: InfobipMessage = Field(discriminator="type")
    contact: InfobipContact | None

class InfobipInboundPayload(BaseModel):
    results: list[InfobipResult]
    message_count: int = Field(alias="messageCount")
```

**Como é usado:**

- O endpoint `POST /bot` (em `app/api/webhook.py`) declara `payload: InfobipInboundPayload` como parâmetro — FastAPI faz parsing + validação automaticamente.

**Pontos não óbvios:**

- **Sempre batch**: o payload do Infobip vem como `{"results": [...]}` mesmo com uma mensagem só. Caller deve iterar.
- **`from` é alias**: `result.sender` no Python corresponde ao campo `from` do JSON. Necessário porque `from` é keyword em Python.
- **Discriminator no `message`**: union discriminado por `type` — Pydantic escolhe `InfobipMessageText` ou `InfobipMessageImage` baseado em `message.type`.
- **Cobertura incompleta**: o Infobip suporta outros tipos (`DOCUMENT`, `AUDIO`, `VIDEO`, `LOCATION`, `CONTACT`, `INTERACTIVE_*`). Não foram modelados porque o bot atual só processa texto e imagem. Quando precisar, adicionar mais sub-schemas ao union `InfobipMessage`.

## O que NÃO está aqui

- **Lógica de envio com retry / fila** — caller é responsável.
- **Status callbacks / delivery reports** — endpoint separado no Infobip, não modelado.
- **Auth do webhook** — implementado via Basic Auth. A dependência FastAPI `verify_infobip_basic_auth` (em `app/api/deps.py`) valida `Authorization: Basic ...` em cada request a `POST /bot`, comparando `secrets.compare_digest` contra `INFOBIP-WEBHOOK-USER`/`INFOBIP-WEBHOOK-PASSWORD` do Key Vault. Fail-safe: 503 se credenciais ausentes, 401 se inválidas.

## `DLQClient`

```python
class DLQClient:
    def __init__(self) -> None: ...
    def enqueue(self, message: DLQMessage) -> bool: ...
    def peek(self, max_messages: int = 32) -> list[dict[str, Any]]: ...
    def receive_one(self) -> Optional[dict[str, Any]]: ...
    def receive_by_id(self, message_id: str) -> Optional[dict[str, Any]]: ...
    def delete(self, message_id: str, pop_receipt: str) -> bool: ...
```

**Como é usado:**

- Singleton em `app.state.dlq` (criado no module-load `main.py` populando `app.state`). Routers acessam via `Depends(get_dlq)` — 503 se `None`.
- `InfobipClient._post` e `AzureBlobService._download_midia` chamam `enqueue` quando o retry transient esgota.
- Endpoints admin (`app/api/admin.py`): `GET /admin/dlq` chama `peek`, `POST /admin/dlq/retry/{id}` chama `receive_by_id` → executa retry via `executar_retry_dlq` (em `deps.py`) → `delete` **sempre** (sucesso ou falha do retry).

**Pontos não óbvios:**

- **Política intencional**: apenas persiste, sem retry automático. Cada mensagem tem 1 ciclo de vida (enqueue → admin retry manual → delete). Evita fila poluída com fantasmas re-tentando sozinhas.
- **Visibility timeout = 5 min** (`RECEIVE_VISIBILITY_SECONDS`): tempo que o admin tem pra processar a mensagem antes de reaparecer.
- **TTL fixo em 7 dias** (default do Storage Queue): mensagens expiram naturalmente se ninguém agir.
- **`receive_by_id` itera todas as páginas**: o Storage Queue não tem primitiva "fetch por ID"; iteramos páginas de 32 mensagens com `visibility_timeout=5s` curto pra inspecionar. Antes da fix `fix/dlq-receive-by-id-pagination` só lia a primeira página (`.by_page().next()`), causando 404 falso pra mensagens nas páginas 2+ quando a fila excedia 32 itens. Custo: O(N/32) chamadas; aceitável porque o admin retry é manual (raro).
- **`enqueue` nunca propaga exceção**: falha em enfileirar é `CRITICAL` log + retorno `False`. Melhor perder a mensagem que travar o caminho normal (caller decide se ainda quer retornar 200).

## `SequenceQueueClient`

```python
class SequenceQueueClient:
    def __init__(self) -> None: ...
    def enqueue(self, sender_id: str, sequence: list[dict]) -> bool: ...
    def receive_one(self) -> Optional[dict[str, Any]]: ...
    def delete(self, message_id: str, pop_receipt: str) -> bool: ...
```

**Como é usado:**

- Singleton instanciado no **lifespan startup** (não no module-load — depende do `Settings` já populado) e armazenado em `app.state.sequence_queue`. Routers acessam via `Depends(get_sequence_queue)` (este getter retorna `None` sem 503 — enqueue é fire-and-forget).
- `app/api/webhook.py`: quando `resposta_bot["tipo"] == "sequencia"`, chama `sequence_queue.enqueue(sender_id, mensagens)`.
- `sequence_worker` (em `app/services/sequence_worker.py`) instancia seu próprio cliente na thread daemon e consome em loop: `receive_one()` → processa → `delete()`.

**Pontos não óbvios:**

- **Visibility timeout = 5 min** + `POISON_THRESHOLD = 5`: se uma sequência falha 5× (dequeue_count > 5), o worker deleta e loga `CRITICAL` (evita loop infinito).
- **Sem ack parcial**: a unidade indivisível é a sequência inteira. Se falha no item 3 de 5, a mensagem reaparece e o worker re-envia os 5 (usuário recebe 1-2 duplicados). Mitigação futura: tracker `sent_index` no payload.
- **Idempotência por mensagem WhatsApp**: o `messageId` da Infobip é gerado server-side, então duplicação na entrega = duas mensagens distintas pro usuário. Aceitável a < 0.1% das sequências.
