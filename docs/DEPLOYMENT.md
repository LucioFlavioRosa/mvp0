# Deployment - Bot Aguas do Para

> Runbook operacional para provisionar, configurar e subir a aplicacao em Azure.
> _Ultima atualizacao: PR `feat/dlq-admin-endpoints` (Storage Queue + 2 secrets admin)._

> Este documento descreve o ambiente atual: **Azure App Service Linux + Python 3.12**. Se o destino mudar (AKS, ACI, Functions), refazer este doc.

## Visao geral

- **Hospedagem**: Azure App Service Linux (plano P1v3 ou superior)
- **Runtime**: Python 3.12 (configurado em `.github/workflows/main_app-aegea-dev-brazil.yml`)
- **Web server**: Gunicorn + UvicornWorker (4 workers, ver `startup.sh`)
- **Banco**: Azure SQL Server (Serverless General Purpose Gen5)
- **Secrets**: Azure Key Vault (acesso via Managed Identity, role `Key Vault Secrets User`)
- **Telemetria**: Application Insights (workspace-based) via `azure-monitor-opentelemetry`
- **Storage de midia**: Azure Blob Storage (containers `documentos-parceiros` e `midia-temporaria`)

Para arquitetura de codigo e decisoes, ver [`ARCHITECTURE.md`](ARCHITECTURE.md).
Para controles de seguranca e LGPD, ver [`Infraestrutura.md`](Infraestrutura.md).

## Ambientes

| Ambiente | Resource Group | Sufixo dos recursos | App Service           |
|---|---|---|---|
| Dev | `rg-aguasdopara-dev` | `-dev` | `app-aegea-dev-brazil.azurewebsites.net` |
| Prod | `rg-aguasdopara-prod` | (a definir) | (a definir) |

> Atualmente apenas o ambiente **dev** existe (configurado via GitHub Actions). O ambiente **prod** sera provisionado seguindo este runbook quando aprovado.

## 1. Pre-requisitos

- Azure CLI 2.50+ (`az --version`)
- Login valido: `az login`
- Permissao Owner ou Contributor no resource group
- Subscription correta: `az account set --subscription <id>`

Para conectar ao SQL:

- `sqlcmd` (parte do mssql-tools) ou Azure Data Studio

## 2. Provisionar recursos (one-time por ambiente)

### 2.1 Resource Group

```bash
ENV=dev   # ou prod
LOCATION=brazilsouth

az group create \
  --name rg-aguasdopara-$ENV \
  --location $LOCATION
```

### 2.2 Azure Key Vault

```bash
KV_NAME=kv-aguasdopara-$ENV

az keyvault create \
  --name $KV_NAME \
  --resource-group rg-aguasdopara-$ENV \
  --location $LOCATION \
  --enable-rbac-authorization true
```

### 2.3 Application Insights

```bash
az monitor app-insights component create \
  --app appi-aguasdopara-$ENV \
  --location $LOCATION \
  --resource-group rg-aguasdopara-$ENV \
  --kind web \
  --application-type web
```

Anote o **connection string** retornado - vai no passo 4 (secret).

### 2.4 Azure SQL Server + Database

```bash
SQL_SERVER=sql-aguasdopara-$ENV
SQL_ADMIN=sqladmin

az sql server create \
  --name $SQL_SERVER \
  --resource-group rg-aguasdopara-$ENV \
  --location $LOCATION \
  --admin-user $SQL_ADMIN \
  --admin-password "<gere-uma-senha-forte>"

az sql db create \
  --name aguasdopara \
  --resource-group rg-aguasdopara-$ENV \
  --server $SQL_SERVER \
  --edition GeneralPurpose \
  --family Gen5 \
  --capacity 2 \
  --compute-model Serverless
```

**Connection string** no codigo nao e um secret unico: o `DatabaseManager` em `app/core/database.py` monta dinamicamente a partir de 4 secrets (`DB-SERVER`, `DB-NAME`, `DB-USER`, `DB-PASSWORD`). Configurar todos no passo 4.

### 2.5 Azure Blob Storage

```bash
STORAGE=staguasdopara$ENV    # storage account names: sem hifen, lowercase, max 24 chars

az storage account create \
  --name $STORAGE \
  --resource-group rg-aguasdopara-$ENV \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2
```

Containers necessarios:

```bash
ACCOUNT_KEY=$(az storage account keys list \
  --resource-group rg-aguasdopara-$ENV \
  --account-name $STORAGE \
  --query '[0].value' -o tsv)

az storage container create \
  --name documentos-parceiros \
  --account-name $STORAGE \
  --account-key $ACCOUNT_KEY \
  --public-access off

az storage container create \
  --name midia-temporaria \
  --account-name $STORAGE \
  --account-key $ACCOUNT_KEY \
  --public-access off
```

Pegar a connection string para o secret do passo 4:

```bash
az storage account show-connection-string \
  --resource-group rg-aguasdopara-$ENV \
  --name $STORAGE \
  --query connectionString -o tsv
```

### 2.6 Azure Storage Queue (Dead-Letter Queue)

Fila para persistir falhas de envio outbound apos esgotamento do retry transient (PR `feat/dlq-persistence` + `feat/dlq-admin-endpoints`).

```bash
az storage queue create \
  --name outbound-dlq \
  --account-name $STORAGE \
  --account-key $ACCOUNT_KEY
```

> A fila reusa a mesma storage account dos containers Blob (mesmo secret `CONNECTION-STRING-AZURE-STORAGE`). A app cria a fila on-demand via `QueueClient.create_queue()` (idempotente), entao este comando e apenas para garantir que existe antes do primeiro envio.

**Caracteristicas da fila:**

- Nome fixo: `outbound-dlq` (codado em `app/integrations/dlq.py:QUEUE_NAME`)
- TTL das mensagens: 7 dias (default + maximo do Storage Queue)
- Visibility timeout no retry admin: 5 min (`RECEIVE_VISIBILITY_SECONDS = 300`)
- Politica: 1 ciclo de vida por mensagem (enqueue -> admin retry manual -> delete obrigatorio)

### 2.7 App Service

```bash
APP_NAME=app-aegea-$ENV-brazil   # dev = "app-aegea-dev-brazil" (igual ao workflow GH atual)
PLAN=plan-aguasdopara-$ENV

az appservice plan create \
  --name $PLAN \
  --resource-group rg-aguasdopara-$ENV \
  --location $LOCATION \
  --sku P1v3 \
  --is-linux

az webapp create \
  --name $APP_NAME \
  --resource-group rg-aguasdopara-$ENV \
  --plan $PLAN \
  --runtime "PYTHON:3.12"

# Habilitar Managed Identity (System-assigned)
az webapp identity assign \
  --name $APP_NAME \
  --resource-group rg-aguasdopara-$ENV
```

Anote o `principalId` retornado.

## 3. Permissoes (Managed Identity -> Key Vault)

```bash
PRINCIPAL_ID=$(az webapp identity show \
  --name $APP_NAME \
  --resource-group rg-aguasdopara-$ENV \
  --query principalId -o tsv)

KV_ID=$(az keyvault show \
  --name $KV_NAME \
  --query id -o tsv)

az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee $PRINCIPAL_ID \
  --scope $KV_ID
```

Use `Secrets User` (so leitura), nao `Secrets Officer` - a app nao cria/altera secrets.

## 4. Configurar secrets no Key Vault

16 secrets devem existir no vault antes do app subir:

| Secret | Origem do valor | Quem cria |
|---|---|---|
| `INFOBIP-API-KEY` | Portal Infobip -> API Keys | DevOps |
| `INFOBIP-BASE-URL` | Portal Infobip -> API endpoint (`https://<id>.api.infobip.com`) | DevOps |
| `INFOBIP-SENDER` | Numero WhatsApp registrado na Infobip (E164 sem prefixo, ex: `551133334444`) | DevOps |
| `INFOBIP-WEBHOOK-USER` | Usuario do perfil Basic Auth no portal Infobip | DevOps |
| `INFOBIP-WEBHOOK-PASSWORD` | Senha do perfil Basic Auth no portal Infobip | DevOps |
| `ADMIN-USER` | Usuario Basic Auth dos endpoints `/admin/*` (DLQ list/retry) | DevOps |
| `ADMIN-PASSWORD` | Senha Basic Auth dos endpoints `/admin/*` | DevOps |
| `AZURE-AD-TENANT-ID` | Portal Azure -> Entra ID -> Overview -> Tenant ID. Usado para validar JWT do `/api/dispatch`. Setup completo em [`AUTH-AZURE-AD.md`](AUTH-AZURE-AD.md). | DevOps |
| `AZURE-AD-API-CLIENT-ID` | Client ID da App Registration "Bot Aguas API" (passo 1 do AUTH-AZURE-AD.md). Identifica esta API no Azure AD. | DevOps |
| `DB-SERVER` | `<sql-server>.database.windows.net` (do passo 2.4) | DevOps |
| `DB-NAME` | `aguasdopara` (do passo 2.4) | DevOps |
| `DB-USER` | `sqladmin` (do passo 2.4) | DevOps |
| `DB-PASSWORD` | Senha do admin SQL (gerada no passo 2.4) | DevOps |
| `CONNECTION-STRING-AZURE-STORAGE` | Output de `az storage account show-connection-string` (passo 2.5). Usado tambem pela DLQ (Storage Queue, passo 2.6). | DevOps |
| `GOOGLE-MAPS-API-KEY` | Google Cloud Console -> APIs & Credentials | DevOps |
| `VIDEO-URL` | URL publica do video de apresentacao (Blob com SAS publica) | Negocio |

Comando para criar um secret:

```bash
az keyvault secret set \
  --vault-name $KV_NAME \
  --name INFOBIP-API-KEY \
  --value "<valor>"

# Repetir para cada linha da tabela acima
```

**Boas praticas:**

- Use variaveis temporarias na shell: `read -s INFOBIP_KEY && az keyvault secret set ... --value "$INFOBIP_KEY" && unset INFOBIP_KEY`
- Nao copie/cole valores em chat/email - prefira sharing seguro (1Password, Bitwarden compartilhado, etc)
- Rotacione periodicamente, especialmente `INFOBIP-WEBHOOK-PASSWORD` apos qualquer incidente

## 5. Configurar App Service Settings

4 variaveis de ambiente nao sao secrets - vao como App Settings:

```bash
APPINSIGHTS_CONN=$(az monitor app-insights component show \
  --app appi-aguasdopara-$ENV \
  --resource-group rg-aguasdopara-$ENV \
  --query connectionString -o tsv)

az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group rg-aguasdopara-$ENV \
  --settings \
    AZURE_KEYVAULT_URL="https://$KV_NAME.vault.azure.net" \
    APPLICATIONINSIGHTS_CONNECTION_STRING="$APPINSIGHTS_CONN" \
    LOG_LEVEL="INFO" \
    LOG_PII_SALT="<gere-uma-string-aleatoria>" \
    SCM_DO_BUILD_DURING_DEPLOYMENT="true"
```

| Variavel | Default | Proposito |
|---|---|---|
| `AZURE_KEYVAULT_URL` | (obrigatorio) | URL do Key Vault - onde a app le secrets via Managed Identity |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | (obrigatorio) | Telemetria estruturada (logs, traces, exceptions) |
| `LOG_LEVEL` | `INFO` | Nivel raiz do logger; trocar para `DEBUG` durante investigacao |
| `LOG_PII_SALT` | (recomendado) | Salt do hash SHA-256 para mascarar PII em logs. Rotacionavel - rotacionar invalida correlacao de logs antigos (intencional). |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Habilita Oryx build (pip install) durante deploy |

Definir startup command:

```bash
az webapp config set \
  --name $APP_NAME \
  --resource-group rg-aguasdopara-$ENV \
  --startup-file "bash startup.sh"
```

### 5.1 Configurar health check do App Service

App Service tem health check nativo que reinicia a instancia se ela ficar
unresponsive. Apontar para `/health/ready` (readiness, NAO liveness):

```bash
az webapp config set \
  --name $APP_NAME \
  --resource-group rg-aguasdopara-$ENV \
  --generic-configurations '{"healthCheckPath": "/health/ready"}'
```

Por que `/health/ready` e nao `/`?
- `GET /` (liveness) sempre retorna 200 enquanto o processo vive. Inutil
  para detectar SQL caido ou Storage offline.
- `GET /health/ready` checa dependencias e retorna 503 se algo falhou.
  App Service para de rotear trafego para a instancia ate normalizar.

Trade-off: durante cold start do Azure SQL Serverless (ate ~1 min), o
endpoint pode oscilar entre 200/503. App Service tem tolerancia padrao
(precisa 3 falhas consecutivas para considerar unhealthy) - ajustar se
o oscilar gerar restarts indesejados.

> O `startup.sh` instala o ODBC Driver 18 (necessario para pyodbc) antes de iniciar o Gunicorn.

## 6. Permitir acesso do App Service ao SQL Server

```bash
az sql server firewall-rule create \
  --name AllowAzureServices \
  --resource-group rg-aguasdopara-$ENV \
  --server $SQL_SERVER \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

Em **prod**, considerar Private Endpoint + VNET integration em vez de allowlist publica.

## 7. Schema SQL inicial

> **Sem migrations versionadas no repo atualmente.** O schema foi criado manualmente no SQL Server. Pretendemos adicionar pasta `migrations/` em PR futura. Por enquanto, as tabelas abaixo devem existir antes do app subir.

Tabelas inferidas do codigo (do `git grep` nos services):

| Tabela | Usada em |
|---|---|
| `CHAT_SESSIONS` | `bot_engine._get_session/_save_session` |
| `PARCEIROS_PERFIL` | `etapa_pessoal`, `etapa_endereco` (CRUD direto via DatabaseManager) |
| `PARCEIROS_DOCS_LEGAIS` | (modulo de documentos) |
| `PARCEIROS_HABILIDADES` | `etapa_habilidades._salvar_background` |
| `PARCEIROS_DISPONIBILIDADE` | `etapa_disponibilidade._salvar_disponibilidade` |
| `PEDIDOS_SERVICO` | `dispatch_service` (origem do pedido) |
| `PEDIDOS_DISPAROS` | `dispatch_service` (rastreio de oferta), `etapa_oferta` |
| `INTERACOES_CHAT` | (logs de auditoria) |

Estrutura detalhada em [`Infraestrutura.md`](Infraestrutura.md) secao 3 (ER Diagram).

Aplicacao manual (Azure Data Studio ou sqlcmd) ate haver migrations versionadas.

> **Recomendacao:** criar pasta `migrations/` com scripts `0001_*.sql` em PR separada, e atualizar este documento com loop em `sqlcmd` (formato em `references/doc-templates.md` da skill `repo-documentation`).

## 8. Deploy do codigo

### Opcao A: GitHub Actions (atual - dev)

O workflow `.github/workflows/main_app-aegea-dev-brazil.yml` ja faz deploy automatico em push para `main`. Configurado para o App Service `app-aegea-dev-brazil`.

Para criar workflow analogo para **prod**, copiar o arquivo dev e ajustar:

- Nome do app
- Publish profile (criar novo no portal Azure e adicionar como GitHub secret)
- Trigger: `push` em tag `v*` ou `workflow_dispatch` manual (evitar auto-deploy em prod a partir de `main`)

### Opcao B: Deploy manual via Azure CLI

Util para hotfix urgente ou ambiente sem CI/CD:

```bash
git archive --format zip HEAD -o /tmp/aguasdopara.zip

az webapp deploy \
  --name $APP_NAME \
  --resource-group rg-aguasdopara-$ENV \
  --src-path /tmp/aguasdopara.zip \
  --type zip
```

## 9. Configurar webhook Infobip

No portal Infobip:

1. **Channels -> WhatsApp -> Configuration -> Set up webhooks**
2. Adicionar evento **INBOUND_MESSAGE** com URL: `https://<app-name>.azurewebsites.net/bot`
3. Em **Security Profile**, criar Basic Auth com usuario/senha
4. **Esses valores devem bater** com `INFOBIP-WEBHOOK-USER` e `INFOBIP-WEBHOOK-PASSWORD` no Key Vault (passo 4)
5. Salvar e testar com "Test webhook" no portal Infobip

## 10. Smoke tests pos-deploy

Apos qualquer deploy, rodar:

```bash
APP_URL=https://app-aegea-$ENV-brazil.azurewebsites.net

# 1. Liveness probe
curl -i $APP_URL/
# Esperado: HTTP/1.1 200 OK + {"status":"online","environment":"Azure Production"}

# 1.1 Readiness probe - checa SQL/Infobip/Storage/Key Vault
curl -i $APP_URL/health/ready
# Esperado: HTTP/1.1 200 OK + {"status":"ok","checks":{"sql":{"status":"ok",...},...}}
# Se vier 503: ler o body para identificar qual check falhou
# - sql down: verificar firewall do SQL Server (passo 6) ou cold start do Serverless
# - infobip down: secrets INFOBIP-* ausentes no Key Vault (passo 4)
# - storage down: secret CONNECTION-STRING-AZURE-STORAGE ausente ou fila outbound-dlq nao existe
# - keyvault down: Managed Identity sem permissao (passo 3) ou Key Vault inacessivel

# 2. Webhook sem auth (deve negar)
curl -i -X POST $APP_URL/bot \
  -H "Content-Type: application/json" \
  -d '{"results":[],"messageCount":0}'
# Esperado: HTTP/1.1 401 Unauthorized
# Se vier 503: secrets INFOBIP-WEBHOOK-USER/PASSWORD nao configurados

# 3. Webhook com auth correta (deve aceitar)
curl -i -X POST $APP_URL/bot \
  -u "<INFOBIP-WEBHOOK-USER>:<INFOBIP-WEBHOOK-PASSWORD>" \
  -H "Content-Type: application/json" \
  -d '{"results":[],"messageCount":0}'
# Esperado: HTTP/1.1 200 OK + {"status":"ok"}

# 4. Logs estruturados aparecem no App Insights
# Portal -> Application Insights -> Transaction search -> filtrar por "operation == webhook_inbound"

# 5. Admin DLQ sem auth (deve negar)
curl -i $APP_URL/admin/dlq
# Esperado: HTTP/1.1 401 Unauthorized
# Se vier 503: secrets ADMIN-USER/ADMIN-PASSWORD nao configurados

# 6. Admin DLQ com auth correta (deve aceitar)
curl -i $APP_URL/admin/dlq -u "<ADMIN-USER>:<ADMIN-PASSWORD>"
# Esperado: HTTP/1.1 200 OK + {"count":0,"messages":[]}  (vazia em ambiente novo)

# 7. Dispatch sem token (deve negar)
curl -i -X POST $APP_URL/api/dispatch \
  -H "Content-Type: application/json" \
  -d '{"pedido_uuid":"test","parceiros":["x"]}'
# Esperado: HTTP/1.1 401 Unauthorized (token Azure AD nao enviado)
# Se vier 503: secrets AZURE-AD-TENANT-ID / AZURE-AD-API-CLIENT-ID ausentes

# 8. Dispatch com token bogus (deve negar)
curl -i -X POST $APP_URL/api/dispatch \
  -H "Authorization: Bearer fake.token.here" \
  -H "Content-Type: application/json" \
  -d '{"pedido_uuid":"test","parceiros":["x"]}'
# Esperado: HTTP/1.1 401 (assinatura JWT invalida)
# Para teste com token REAL, ver docs/AUTH-AZURE-AD.md secao "Smoke test pos-deploy"
```

Se algum smoke test falhar, ver passo 12 (troubleshooting).

## 11. Rollback

> **Pre-requisito**: ter slot `staging` configurado antes (atualmente nao temos - configurar pode ser PR separada).

Com slot configurado:

```bash
az webapp deployment slot swap \
  --name $APP_NAME \
  --resource-group rg-aguasdopara-$ENV \
  --slot staging \
  --target-slot production
```

Sem slot (workaround atual):

```bash
# 1. Reverter o commit no GitHub
git revert <commit-do-deploy-ruim>
git push origin main

# 2. GitHub Actions automaticamente redeploya
```

Para mudancas de schema SQL, rollback manual com os comentarios `-- Rollback:` quando houver migrations versionadas.

## 12. Troubleshooting

| Sintoma | Diagnostico | Solucao |
|---|---|---|
| App nao inicia (HTTP 500 no `/`) | `az webapp log tail -n $APP_NAME -g rg-aguasdopara-$ENV` | Geralmente secret faltando ou `AZURE_KEYVAULT_URL` errada |
| 503 no `/bot` | `verify_infobip_basic_auth` reclama de secrets ausentes | Confirmar `INFOBIP-WEBHOOK-USER`/`PASSWORD` no Key Vault |
| 401 nas chamadas legitimas do Infobip | Usuario/senha diferentes entre portal Infobip e Key Vault | Re-sincronizar (passo 4 + 9) |
| 503 em `/admin/dlq*` | `verify_admin_basic_auth` reclama de secrets ausentes | Confirmar `ADMIN-USER`/`ADMIN-PASSWORD` no Key Vault (passo 4) |
| 503 em `/api/dispatch` | Secrets AZURE-AD ausentes ou scheme nao inicializou | Confirmar `AZURE-AD-TENANT-ID` e `AZURE-AD-API-CLIENT-ID` no Key Vault. Ver log "Azure AD auth nao inicializado" em App Insights |
| 401 em `/api/dispatch` com token aparentemente valido | Claim do JWT errado (audience, issuer ou scope) | Decodificar token em jwt.ms e conferir: `aud` = `api://<azure-ad-api-client-id>`, `scp` contem `dispatch.write`. Ver `docs/AUTH-AZURE-AD.md` secao Troubleshooting |
| 404 em `POST /admin/dlq/retry/{id}` mesmo com mensagem visivel em `GET /admin/dlq` | Mensagem pode estar com visibility timeout ativo (alguem chamou retry recentemente) ou TTL expirou | Aguardar 5 min ou re-listar para pegar o ID atual |
| Mensagens "fantasma" reaparecendo na DLQ | `delete()` falhou pos-retry (pop_receipt mismatch) | Ver log `falha ao deletar mensagem da DLQ` no App Insights; geralmente significa que outro admin processou em paralelo - re-tentar |
| `pyodbc.OperationalError` SQL | Cold start do Serverless | Aguardar retry exponencial do `DatabaseManager` (ate ~1min); subsequente requests funcionam |
| Midia inbound retorna 401 ao baixar | Header `Authorization: App <key>` invalido ou URL exige outro auth | Confirmar `INFOBIP-API-KEY`. Se URLs sao publicas no tenant, remover header em `azure_blob_service.py:66` |
| Logs nao aparecem no App Insights | `APPLICATIONINSIGHTS_CONNECTION_STRING` errada ou ausente | Confirmar App Setting + restart |
| `ImportError: No module named pyodbc` | ODBC Driver 18 nao instalado | `startup.sh` deve rodar; ver logs do `apt-get install` |

Comandos diagnosticos:

```bash
# Stream logs em tempo real
az webapp log tail -n $APP_NAME -g rg-aguasdopara-$ENV

# Restart do app
az webapp restart -n $APP_NAME -g rg-aguasdopara-$ENV

# Listar secrets do Key Vault (apenas nomes)
az keyvault secret list --vault-name $KV_NAME --output table

# Ver App Settings atuais
az webapp config appsettings list -n $APP_NAME -g rg-aguasdopara-$ENV

# Confirmar identidade Managed e roles
az webapp identity show -n $APP_NAME -g rg-aguasdopara-$ENV
az role assignment list --assignee $PRINCIPAL_ID --scope $KV_ID
```

## Checklist de release

- [ ] Branch da feature mergeada em `main`
- [ ] Migracoes SQL aplicadas em ordem (quando houver `migrations/`)
- [ ] Secrets novos (se houver) criados no Key Vault
- [ ] App Settings novos (se houver) configurados
- [ ] Smoke tests do passo 10 passaram
- [ ] App Insights mostra eventos recentes sem erros novos
- [ ] Webhook Infobip ainda funciona (mande mensagem teste via WhatsApp)
- [ ] Rollback plan documentado no PR (qual commit reverter, qual schema reverter)

## Pontos de fragilidade conhecidos (referenciados para correcao futura)

Para contexto, ver tambem `ARCHITECTURE.md` -> Pontos de fragilidade.

1. **Endpoint `/api/dispatch` sem autenticacao** - publico. Configurar IP allowlist no Front Door ou Basic Auth analogo ao `/bot`.
2. **Migracoes SQL nao versionadas** - schema gerenciado manualmente. Criar pasta `migrations/` e versionar.
3. **Sem ambiente prod ativo** - workflow GH so cobre dev. Provisionar prod via este runbook quando aprovado.
4. **Sem slot staging** - rollback so via revert no Git. Configurar slot para swap.
5. **Mock de validacao CNPJ em producao** - inline em `etapa_pessoal.processar_cnpj` (regra fake "termina em 0000 e invalido"). Integrar Serpro/Receita Federal real antes de go-live. (ViaCEP e Google Maps ja sao reais em `etapa_endereco.py`.)

## Atualizacao deste documento

Sempre que adicionar:

- **Nova env var** -> atualizar tabela passo 5
- **Novo secret** -> atualizar tabela passo 4
- **Nova migracao SQL** -> mencionar no passo 7
- **Nova integracao externa** -> mencionar em pre-requisitos
- **Mudanca de stack** (App Service -> AKS, etc) -> revisar todas as secoes

Use a skill `repo-documentation` (modo update) para detectar drift automaticamente quando houver mudanca no codigo.
