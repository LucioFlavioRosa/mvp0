# Bot Águas do Pará

> Bot WhatsApp para credenciamento de prestadores de serviço (parceiros) no programa Águas do Pará. Aplicação FastAPI em Azure, integrada via Infobip.

## O que é

Plataforma que orquestra o ciclo de vida de prestadores terceiros: onboarding via chat, validação documental, recebimento de ofertas de serviço e rastreio de aceites. O parceiro interage 100% via WhatsApp; o backoffice notifica via API; tudo persiste em Azure SQL.

## Stack

- **Linguagem**: Python 3.11+
- **Framework**: FastAPI + Uvicorn (com Gunicorn em produção)
- **Banco**: Azure SQL Server (via `pyodbc` + ODBC Driver 18)
- **Cloud**: Azure (App Service Linux, Key Vault, Blob Storage)
- **WhatsApp**: Infobip (API REST)
- **Telemetria**: Application Insights via `azure-monitor-opentelemetry` (auto-instrumentação FastAPI/requests/pyodbc)

## Setup local

Pré-requisitos:

- Python 3.11+
- ODBC Driver 18 for SQL Server ([instruções da Microsoft](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server))
- Acesso ao Azure Key Vault de dev (autenticação via `az login` ou Managed Identity)

Passos:

```bash
git clone git@github.com:LucioFlavioRosa/mvp0.git
cd mvp0
python -m venv .venv

# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Aponta para o vault de dev
export AZURE_KEYVAULT_URL=https://<seu-vault>.vault.azure.net   # Linux/macOS
# $env:AZURE_KEYVAULT_URL = "https://..."                       # PowerShell

az login    # autentica DefaultAzureCredential

uvicorn main:app --reload --port 8000
```

App disponível em `http://localhost:8000`. Swagger interativo em `http://localhost:8000/docs`.

Smoke test:

```bash
# Health check
curl http://localhost:8000/

# Webhook mock (formato Infobip)
curl -X POST http://localhost:8000/bot \
  -H "Content-Type: application/json" \
  -d '{
    "results": [{
      "from": "5511999998888",
      "to": "551133334444",
      "messageId": "test-001",
      "receivedAt": "2026-05-12T12:00:00Z",
      "message": {"type": "TEXT", "text": "oi"}
    }],
    "messageCount": 1
  }'
```

## Variáveis de ambiente e secrets

Variáveis de ambiente são lidas diretamente; segredos vivem no Azure Key Vault.

| Local | Nome | Uso |
|---|---|---|
| env var | `AZURE_KEYVAULT_URL` | URL do Key Vault (obrigatório) |
| env var | `APPLICATIONINSIGHTS_CONNECTION_STRING` | Conexão com Application Insights (telemetria estruturada) |
| env var | `LOG_LEVEL` | Nível de log (default `INFO`) — `DEBUG` em investigação |
| env var | `LOG_PII_SALT` | Salt do hash SHA-256 para mascarar PII (LGPD) — rotacionável |
| Key Vault | `INFOBIP-API-KEY` | Auth da API Infobip |
| Key Vault | `INFOBIP-BASE-URL` | Endpoint do tenant Infobip (`https://<id>.api.infobip.com`) |
| Key Vault | `INFOBIP-SENDER` | Número remetente E164 sem prefixo |
| Key Vault | `INFOBIP-WEBHOOK-USER` | Usuário Basic Auth do webhook `/bot` (deve bater com o portal Infobip) |
| Key Vault | `INFOBIP-WEBHOOK-PASSWORD` | Senha Basic Auth do webhook `/bot` |
| Key Vault | `DB-SERVER` | Endereço do SQL Server |
| Key Vault | `DB-NAME` | Nome do banco |
| Key Vault | `DB-USER` | Usuário SQL |
| Key Vault | `DB-PASSWORD` | Senha SQL |
| Key Vault | `CONNECTION-STRING-AZURE-STORAGE` | Connection string do Blob |

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Health check (responde `{"status": "online"}`) |
| `POST` | `/bot` | Webhook inbound do Infobip — recebe mensagens do WhatsApp |
| `POST` | `/api/dispatch` | Backoffice notifica parceiros sobre novo pedido |

Lista completa em Swagger (`/docs`).

## Estrutura

```
mvp0/
├── main.py                          # Entry FastAPI: webhook + dispatch
├── app/
│   ├── bot_engine.py                # Orquestrador FSM do chat
│   ├── core/         (config, database, telemetry, log_dimensions)
│   ├── integrations/ (infobip — cliente HTTP)
│   ├── schemas/      (infobip_webhook — Pydantic)
│   ├── services/     (5 services: whatsapp, dispatch, blob, parceiro, session)
│   └── modules/      (onboarding + 7 etapas de cadastro + helper)
├── docs/
│   ├── ARCHITECTURE.md              # Arquitetura de código (este projeto)
│   ├── Infraestrutura.md            # Arquitetura de infra/segurança Azure
│   └── modules/                     # Doc por módulo
├── requirements.txt
└── startup.sh                       # Script de deploy (Azure App Service)
```

Detalhes em [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) e docs por módulo em [`docs/modules/`](docs/modules/).

## Deploy

A aplicação roda em Azure App Service (Linux). O `startup.sh` instala o ODBC Driver 18 e sobe via `gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app`.

Configurar no App Service:

1. **Application Settings**:
   - `AZURE_KEYVAULT_URL` (apontando pro vault de prod)
   - `APPLICATIONINSIGHTS_CONNECTION_STRING` (do recurso App Insights no portal Azure)
   - `LOG_LEVEL=INFO` (default; trocar pra `DEBUG` durante investigação)
   - `LOG_PII_SALT` (rotacionável — definir no Key Vault e referenciar via App Settings)
   - Startup command: `bash startup.sh`
2. **Managed Identity** habilitada — usa `DefaultAzureCredential` pra ler do Key Vault.
3. **Webhook do Infobip** apontando pra `https://<your-app>.azurewebsites.net/bot`.

## Documentação adicional

- [Arquitetura de código](docs/ARCHITECTURE.md) — componentes, fluxos, decisões
- [Arquitetura de infraestrutura](docs/Infraestrutura.md) — Azure, segurança, LGPD
- [Documentação por módulo](docs/modules/) — referência detalhada de cada pasta

## Contribuindo

- Commits seguem [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `chore:`, `docs:`).
- PRs precisam de review antes do merge — a branch `main` é protegida.
- Para mudanças não triviais, abrir issue antes para discutir abordagem.
