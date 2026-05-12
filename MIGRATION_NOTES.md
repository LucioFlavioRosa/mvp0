# MIGRATION_NOTES — Twilio → Infobip

> Documenta a migração da integração WhatsApp do Twilio para o Infobip.
> Pode ser deletado após o PR ser mergeado e os itens manuais resolvidos.

## Resumo

- **4 arquivos** modificados (`main.py`, `app/services/dispatch_service.py`, `app/services/azure_blob_service.py`, `requirements.txt`)
- **1 arquivo** renomeado (`app/services/twilio_service.py` → `app/services/whatsapp_service.py`)
- **2 arquivos** novos (`app/integrations/infobip.py`, `app/schemas/infobip_webhook.py`)
- **1 dep** removida (`twilio`), 0 adicionadas (usa `requests` que já existia)
- **3 secrets** do Key Vault removidos, **3** novos

## Mudanças por arquivo

### `main.py`
- Removidos imports de `twilio.twiml.messaging_response.MessagingResponse` e `twilio.rest.Client`.
- Adicionados imports de `InfobipClient` e `InfobipInboundPayload`.
- Bloco de init Twilio (com lógica do prefixo `whatsapp:`) substituído por init do `InfobipClient` usando `INFOBIP-API-KEY`, `INFOBIP-BASE-URL` e `INFOBIP-SENDER`.
- `enviar_sequencia_background`:
  - Argumento `bot_number` removido (sender é fixo via `INFOBIP-SENDER`).
  - `client.messages.create(...)` substituído por `client.send_text` / `send_image` / `send_template`.
- `chat_webhook`:
  - Parsing de `request.form()` substituído por Pydantic `InfobipInboundPayload`.
  - Removido todo fallback TwiML (`MessagingResponse`, `<Response><Message>`, `media_type="application/xml"`).
  - 2 chamadas `client.messages.create(...)` substituídas pelos métodos do `InfobipClient`.
  - Iteração por `payload.results` (Infobip sempre manda batch).
  - Retorno: `{"status": "ok"}`.

### `app/services/twilio_service.py` → `app/services/whatsapp_service.py`
- Arquivo renomeado, classe `TwilioService` → `WhatsAppService`.
- Internamente usa `InfobipClient` em vez de `twilio.rest.Client`.
- Interface pública (`enviar_resposta`) **preservada** — `DispatchService` e outros callers continuam funcionando sem mudança de assinatura.
- Lógica de strip de prefixo `whatsapp:` movida pra função utilitária.
- Adicionada constante `DEFAULT_TEMPLATE_LANGUAGE = "pt_BR"` (Infobip exige `language` explícita).
- Helper `_dict_to_positional_list` mantém retrocompatibilidade com chamadores que ainda passam `variaveis={'1': ..., '2': ...}` no estilo Twilio.

### `app/services/dispatch_service.py`
- Import e atributo: `TwilioService` → `WhatsAppService`, `self.twilio` → `self.whatsapp`.
- `TEMPLATE_OFERTA`: `"HXe06780de5d2ec3b456c82275071f6bfc"` → `"oferta_servico"` (placeholder — ver item 1 abaixo).
- `variaveis_template` (dict) → `placeholders` (list, ordem posicional).
- Payload de mensagem: `{'sid', 'variaveis'}` → `{'template_name', 'placeholders'}`.

### `app/services/azure_blob_service.py`
- Secrets `TWILIO-ACCOUNT-SID` + `TWILIO-AUTH-TOKEN` substituídos por `INFOBIP-API-KEY`.
- Header HTTP: `auth=(sid, token)` (Basic Auth) → `headers={"Authorization": "App <key>"}`.
- Logs/comentários atualizados: "Twilio" → "Infobip".

### `requirements.txt`
- Removido `twilio>=8.0.0`.

### Novos arquivos
- `app/integrations/infobip.py` — `InfobipClient` (wrapper HTTP fino sobre `requests`, com `send_text` / `send_image` / `send_template`).
- `app/schemas/infobip_webhook.py` — `InfobipInboundPayload` + sub-schemas Pydantic.

## Secrets do Azure Key Vault

⚠ **Atualizar antes do deploy.** A skill não tem acesso ao Key Vault — você precisa fazer no portal Azure.

Remover:
- `TWILIO-ACCOUNT-SID`
- `TWILIO-AUTH-TOKEN`
- `TWILIO-PHONE-NUMBER`

Adicionar:
- `INFOBIP-API-KEY` — chave gerada no portal Infobip
- `INFOBIP-BASE-URL` — formato `https://<seu-id>.api.infobip.com` (varia por tenant)
- `INFOBIP-SENDER` — número remetente E164 sem prefixo (ex: `551133334444`)

Atualizar também variáveis em `.env` local e em CI/CD se houver.

## ⚠ Revisar manualmente

### 1. Template `oferta_servico` precisa ser cadastrado no portal Infobip

`dispatch_service.py:11` usava o SID Twilio `HXe06780de5d2ec3b456c82275071f6bfc` com 9 placeholders. No Infobip:

1. Cadastrar o template no portal com a mesma ordem de placeholders:
   1. `primeiro_nome`
   2. `atividade`
   3. `numero`
   4. `rua`
   5. `bairro`
   6. `data_fmt`
   7. `observacao`
   8. `valor_fmt`
   9. `urgencia`
2. Idioma: `pt_BR` (constante `DEFAULT_TEMPLATE_LANGUAGE` em `whatsapp_service.py`).
3. Quando o template for aprovado, atualizar `TEMPLATE_OFERTA = "oferta_servico"` em `dispatch_service.py` para o nome real definido no portal (se for diferente).

Sem isso, `/api/dispatch` retorna sucesso mas o envio falha.

### 2. Webhook sem validação de assinatura

`main.py:115` (`@app.post("/bot")`) é público sem auth. Migração é boa oportunidade pra:

- Configurar Basic Auth no portal Infobip (a config fica em **Channels → WhatsApp → Webhook**)
- Validar no FastAPI com `Depends(HTTPBasic(...))` ou middleware
- Ou alternativamente: configurar IP allowlist no Azure App Service

### 3. Sem fallback de resposta — falhas no envio são silenciosas pro usuário

Antes (Twilio): se `messages.create` falhava, o handler retornava TwiML como salvaguarda. Hoje (Infobip): se `send_text`/`send_template` falham, só sai log de erro — o usuário do WhatsApp **não recebe nada**.

Opções pra mitigar:

- Adicionar retry com `tenacity` (ex: 3 tentativas, exponential backoff) nas chamadas do `InfobipClient`.
- Enfileirar mensagens não enviadas (Azure Service Bus, Redis) pra reprocessar.
- Métricas/alertas no Application Insights quando taxa de falha sobe.

Decisão fora do escopo desta migração — ver issue separada.

### 4. Bug existente corrigido na migração: `TWILIO-PHONE-NUMBER` vs `TWILIO_PHONE_NUMBER`

O código antigo misturava o secret com hífen (linha 45 do `main.py` original) com versão com underscore (linhas 78 e 143). Provavelmente só o com hífen existia no Key Vault — o fallback retornava `None` silenciosamente.

A migração unifica em `INFOBIP-SENDER` único, lido uma vez no startup. Verificar se o multi-tenant é necessário (item 5).

### 5. `bot_number` dinâmico removido

`main.py:121` original pegava `bot_number = form_data.get('To', '')` e usava como sender. No Infobip o sender é fixo via `INFOBIP-SENDER`.

Como o bot é único ("Águas do Pará"), uso `sender_number` global. Se no futuro houver múltiplos números de bot, será necessário reintroduzir lookup dinâmico (e configurar múltiplos senders no Infobip).

### 6. Auth de download de mídia no `azure_blob_service.py`

A skill aplicou `Authorization: App <api_key>` como header default. Dependendo da config do tenant Infobip, as URLs de mídia podem ser:

- **Privadas** — header é necessário (caso default aplicado).
- **Públicas** — header pode causar 401/403 dependendo do CDN.

**Após primeiro deploy**, testar download de mídia. Se receber 401/403, remover o argumento `headers=...` da chamada `requests.get(...)`.

## Como validar localmente antes do deploy

```powershell
cd C:\Users\LucioFlavio\projetos\mvp0
pip install -r requirements.txt

# Configurar variáveis de ambiente locais apontando pro Key Vault de dev
# (ou usar valores mock no .env local)

# Rodar a aplicação
uvicorn main:app --reload --port 8000

# Health check
curl http://localhost:8000/

# Simular webhook Infobip (payload mock)
curl -X POST http://localhost:8000/bot \
  -H "Content-Type: application/json" \
  -d '{"results":[{"from":"5511999998888","to":"551133334444","messageId":"abc","receivedAt":"2026-05-11T12:00:00Z","message":{"type":"TEXT","text":"oi"}}],"messageCount":1}'
```

## Checklist de release

- [ ] Templates do WhatsApp cadastrados no portal Infobip
- [ ] Secrets atualizados no Key Vault de dev e prod
- [ ] Webhook configurado no portal Infobip apontando pra `/bot`
- [ ] Autenticação do webhook configurada (Basic Auth ou IP allowlist)
- [ ] Teste smoke: envio inbound (texto) → resposta outbound
- [ ] Teste smoke: envio inbound (imagem) → upload no Blob funciona
- [ ] Teste do endpoint `/api/dispatch` com 1 parceiro
- [ ] Métrica de falha de envio configurada no Application Insights
- [ ] Decisão sobre retry/queue documentada (item 3)
