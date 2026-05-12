# Módulo: integrations + schemas

> Camada de saída/entrada para a API WhatsApp do Infobip. Combina o cliente HTTP (`integrations/`) e os schemas Pydantic de webhook inbound (`schemas/`).

## Propósito

Isola toda a comunicação com o Infobip. Outro código (services, main) usa esta camada — não fala HTTP direto. Trocar de provedor (Infobip → outro) deveria afetar **só estes dois arquivos**.

## Estrutura

| Arquivo | Classe / Schema | Responsabilidade |
|---|---|---|
| `app/integrations/infobip.py` | `InfobipClient` | Envia requests autenticados pra API Infobip |
| `app/schemas/infobip_webhook.py` | `InfobipInboundPayload` + sub-schemas | Valida e tipa o payload JSON do webhook inbound |

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

- Instanciado uma vez no `main.py` (global) e uma vez no `WhatsAppService.__init__`.
- Re-usa uma `requests.Session` — connection pooling via HTTPS keep-alive.

**Pontos não óbvios:**

- **Auth**: header `Authorization: App <api_key>` — não é Basic Auth (diferente do Twilio antigo).
- **Números**: o `sender` e `to` são E164 sem prefixo `whatsapp:` nem `+` (ex: `5511999998888`). Strip de prefixo é responsabilidade do caller (`WhatsAppService._strip_whatsapp_prefix`).
- **`send_template`**: usa array `placeholders` (posicional), não dict por chave como o Twilio (`content_variables`). A ordem é a do template cadastrado no portal Infobip.
- **Erros 4xx/5xx**: `raise_for_status()` levanta `requests.HTTPException`. Caller decide se faz retry ou loga e segue.
- **Sem retry interno**: o client é intencionalmente fino. Adicionar retry (com `tenacity`) ficaria a cargo do caller — ver "Pontos de fragilidade" em [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md).

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

- O endpoint `POST /bot` em `main.py` declara `payload: InfobipInboundPayload` como parâmetro — FastAPI faz parsing + validação automaticamente.

**Pontos não óbvios:**

- **Sempre batch**: o payload do Infobip vem como `{"results": [...]}` mesmo com uma mensagem só. Caller deve iterar.
- **`from` é alias**: `result.sender` no Python corresponde ao campo `from` do JSON. Necessário porque `from` é keyword em Python.
- **Discriminator no `message`**: union discriminado por `type` — Pydantic escolhe `InfobipMessageText` ou `InfobipMessageImage` baseado em `message.type`.
- **Cobertura incompleta**: o Infobip suporta outros tipos (`DOCUMENT`, `AUDIO`, `VIDEO`, `LOCATION`, `CONTACT`, `INTERACTIVE_*`). Não foram modelados porque o bot atual só processa texto e imagem. Quando precisar, adicionar mais sub-schemas ao union `InfobipMessage`.

## O que NÃO está aqui

- **Lógica de envio com retry / fila** — caller é responsável.
- **Status callbacks / delivery reports** — endpoint separado no Infobip, não modelado.
- **Auth do webhook** (Basic Auth) — não implementado. Ver `MIGRATION_NOTES.md` item 2.
