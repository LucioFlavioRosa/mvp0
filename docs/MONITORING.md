# Monitoramento e Alertas — Bot Águas do Pará

> Setup de alertas operacionais no Azure Monitor / Application Insights. Pré-requisito: Application Insights provisionado (`docs/DEPLOYMENT.md` passo 2.3) e a app já enviando telemetria estruturada (já implementado via `app/core/telemetry.py`).

## Conceitos

| Termo | Significado |
|---|---|
| **Action Group** | Lista de destinatários e canais (email, SMS, Teams). Reusável entre várias regras. |
| **Alert Rule** | Regra que dispara quando query Kusto retorna acima/abaixo do threshold. |
| **Severity** | 0 = crítico (acorda alguém), 1 = importante, 2 = atenção, 3 = informativa, 4 = verbosa. |
| **Action** | O que acontece quando regra dispara — geralmente notificar Action Group. |

## Passo 1 — Criar Action Group

Define quem é notificado. **Substituir os 3 emails pelos endereços reais do time DevOps Aegea.**

```bash
ENV=prod   # ou dev
RG=rg-aguasdopara-$ENV

az monitor action-group create \
  --name ag-aguasdopara-devops-$ENV \
  --resource-group $RG \
  --short-name "AguasDevOps" \
  --action email devops-lead "devops-lead@aegea.com.br" \
  --action email devops-2 "devops-2@aegea.com.br" \
  --action email devops-3 "devops-3@aegea.com.br"
```

> **Dica**: usar uma lista de distribuição (`devops-aguasdopara@aegea.com.br`) em vez de emails individuais facilita rotação de pessoas no time sem precisar atualizar o Action Group.

Anotar o **resource ID** retornado — usado em todos os alertas abaixo:

```bash
AG_ID=$(az monitor action-group show \
  --name ag-aguasdopara-devops-$ENV \
  --resource-group $RG \
  --query id -o tsv)
echo $AG_ID
```

## Passo 2 — Pegar resource ID do Application Insights

```bash
APPI_ID=$(az monitor app-insights component show \
  --app appi-aguasdopara-$ENV \
  --resource-group $RG \
  --query id -o tsv)
```

## Passo 3 — Criar Alert Rules

Cada regra abaixo é um comando `az monitor scheduled-query create`. Categorizadas por severidade.

### Sev 1 (incidente em horário comercial)

#### 1. `/health/ready` retornando 503

```bash
az monitor scheduled-query create \
  --name "mvp0-health-ready-503-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 1 \
  --evaluation-frequency 5m \
  --window-size 5m \
  --condition "count > 5" \
  --condition-query 'requests | where url endswith "/health/ready" and resultCode == "503"' \
  --action $AG_ID \
  --description "App reportando que alguma dependencia (SQL/Infobip/Storage/KV) esta down. Ver body do /health/ready pra detalhe."
```

#### 2. Erros 5xx no `/bot` (webhook Infobip)

```bash
az monitor scheduled-query create \
  --name "mvp0-bot-5xx-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 1 \
  --evaluation-frequency 5m \
  --window-size 5m \
  --condition "count > 10" \
  --condition-query 'requests | where url endswith "/bot" and toint(resultCode) >= 500' \
  --action $AG_ID \
  --description "Webhook Infobip recebendo 5xx. Mensagens dos parceiros nao processadas. Investigar exception em App Insights."
```

#### 3. DLQ crescendo rapidamente

```bash
az monitor scheduled-query create \
  --name "mvp0-dlq-growth-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 1 \
  --evaluation-frequency 5m \
  --window-size 10m \
  --condition "count > 20" \
  --condition-query 'traces | where customDimensions.operation == "dlq_enqueue"' \
  --action $AG_ID \
  --description "20+ mensagens caindo na DLQ em 10 min - sinal de problema externo (Infobip down ou Storage rejeitando). Rodar scripts/dlq-list.sh + investigar last_error."
```

#### 4. Tentativas falhadas de admin auth (suspeita de brute force)

```bash
az monitor scheduled-query create \
  --name "mvp0-admin-auth-brute-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 1 \
  --evaluation-frequency 5m \
  --window-size 5m \
  --condition "count > 10" \
  --condition-query 'traces | where customDimensions.operation == "admin_auth" and customDimensions.result == "unauthorized"' \
  --action $AG_ID \
  --description "10+ falhas de auth em 5min em /admin/*. Possivel brute force. Verificar IP de origem em App Insights + considerar rotacao de ADMIN-PASSWORD."
```

### Sev 2 (atenção, investigar em horas)

#### 5. SQL latency p95 alto

```bash
az monitor scheduled-query create \
  --name "mvp0-sql-latency-high-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 2 \
  --evaluation-frequency 10m \
  --window-size 15m \
  --condition "max > 2000" \
  --condition-query 'dependencies | where type == "SQL" | summarize p95=percentile(duration, 95) by bin(timestamp, 5m) | project value=p95' \
  --action $AG_ID \
  --description "SQL p95 > 2s. Pode ser cold start do Serverless (aceitavel se isolado) ou contention. Ver Azure SQL Insights."
```

#### 6. Infobip retornando 4xx

```bash
az monitor scheduled-query create \
  --name "mvp0-infobip-4xx-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 2 \
  --evaluation-frequency 10m \
  --window-size 15m \
  --condition "count > 5" \
  --condition-query 'traces | where customDimensions.operation in ("send_text", "send_template", "send_image") | where toint(customDimensions.external_status) between (400 .. 499)' \
  --action $AG_ID \
  --description "Infobip rejeitando requests com 4xx. Geralmente: template_name nao cadastrado no portal, ou api_key invalida. Validar config no portal Infobip + INFOBIP-API-KEY no Key Vault."
```

#### 7. Rate limit sendo atingido com frequencia

```bash
az monitor scheduled-query create \
  --name "mvp0-rate-limit-hits-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 2 \
  --evaluation-frequency 15m \
  --window-size 15m \
  --condition "count > 50" \
  --condition-query 'requests | where resultCode == "429"' \
  --action $AG_ID \
  --description "50+ requests bloqueadas por rate limit em 15min. Pode ser: trafego legitimo crescendo (calibrar limites), bug em frontend (loop), ou ataque inicial. Ver IP + endpoint em App Insights."
```

#### 8. CPU > 80% sustained no App Service

```bash
APP_NAME=app-aegea-$ENV-brazil
APP_ID=$(az webapp show --name $APP_NAME --resource-group $RG --query id -o tsv)

az monitor metrics alert create \
  --name "mvp0-cpu-high-$ENV" \
  --resource-group $RG \
  --scopes $APP_ID \
  --severity 2 \
  --evaluation-frequency 5m \
  --window-size 15m \
  --condition "avg CpuPercentage > 80" \
  --action $AG_ID \
  --description "CPU sustentado > 80% por 15 min. Avaliar scale up (P1v3 -> P2v3) ou scale out (mais instancias)."
```

### Sev 3 (informativa, review semanal)

#### 9. Mock de CNPJ ainda em uso

```bash
az monitor scheduled-query create \
  --name "mvp0-mock-cnpj-reminder-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 3 \
  --evaluation-frequency 1h \
  --window-size 24h \
  --condition "count > 0" \
  --condition-query 'traces | where customDimensions.mock == "True" and customDimensions.operation == "validate_cnpj"' \
  --action $AG_ID \
  --description "Validacao de CNPJ ainda usando mock. Lembrete pra integrar Serpro/Receita Federal antes de scale-up."
```

#### 10. Cold starts do SQL Serverless

```bash
az monitor scheduled-query create \
  --name "mvp0-sql-coldstart-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 3 \
  --evaluation-frequency 1h \
  --window-size 24h \
  --condition "count > 5" \
  --condition-query 'dependencies | where type == "SQL" and duration > 30000' \
  --action $AG_ID \
  --description "5+ cold starts (>30s) por dia. Se persistente, considerar promover Serverless -> DTU fixo (mais caro mas sem cold start) ou keep-alive scheduled."
```

#### 11. Vazamento de PII (LGPD sanity check)

```bash
az monitor scheduled-query create \
  --name "mvp0-pii-leak-$ENV" \
  --resource-group $RG \
  --scopes $APPI_ID \
  --severity 1 \
  --evaluation-frequency 1h \
  --window-size 24h \
  --condition "count > 0" \
  --condition-query 'traces | where message matches regex @"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"' \
  --action $AG_ID \
  --description "Possivel CPF/CNPJ em texto plano em log. CRITICO LGPD. Localizar log fonte e mascarar com mask_pii(). Considerar rotacionar LOG_PII_SALT se vazamento confirmado."
```

> **Nota**: este último é **Sev 1** apesar de roda como informativa diária — vazamento de PII em log é incidente regulatório.

## Passo 4 — Validar que alertas estão ativos

```bash
# Listar todas as regras configuradas
az monitor scheduled-query list --resource-group $RG -o table
az monitor metrics alert list --resource-group $RG -o table

# Ver detalhes de uma regra
az monitor scheduled-query show --name "mvp0-health-ready-503-$ENV" --resource-group $RG
```

## Passo 5 — Testar Action Group (forçar email de teste)

Antes de confiar no setup, confirme que os emails chegam. Pelo portal:

1. Azure Portal → Monitor → Action Groups → selecionar `ag-aguasdopara-devops-$ENV`
2. Botão **Test action group** → seleciona "Email" → clica **Test**
3. Os 3 destinatários devem receber email em até 1-2 min com subject "Test alert from..."
4. Se não receber: confirmar que email não caiu em spam; checar `Properties → Notification settings`

## Passo 6 — (Opcional) Dashboard consolidado

Criar dashboard no Azure Portal mostrando os principais sinais. Comando `az portal dashboard create` aceita ARM template, mas mais simples é criar via portal:

1. Azure Portal → **Dashboards** → **+ New dashboard**
2. Adicionar tiles:
   - Métricas: CPU/Memory do App Service
   - Application Insights: Failed requests, Server response time, Failed dependencies
   - Custom query: contagem de mensagens DLQ último 24h
   - Custom query: dispatches por operador (via `customDimensions.operator_oid`)
3. Compartilhar com o time DevOps

## Runbook básico de incidente

Quando um alerta dispara, seguir:

| Alerta | Ação imediata |
|---|---|
| `mvp0-health-ready-503` | `curl $APP_URL/health/ready` → ler body, identificar qual check (sql/infobip/storage/keyvault) está down |
| `mvp0-bot-5xx` | App Insights → Failures → filtrar `/bot` → ver exception. Geralmente: DB connection ou bug Pydantic |
| `mvp0-dlq-growth` | Rodar `scripts/dlq-list.sh` (DEPLOYMENT.md 12.1) → identificar pattern de erro. Se Infobip down, esperar normalizar + retry mass. |
| `mvp0-admin-auth-brute` | App Insights → filtrar `operation == "admin_auth"` AND `result == "unauthorized"` → identificar IP. Considerar rotacionar `ADMIN-PASSWORD` + adicionar IP no WAF/Front Door. |
| `mvp0-sql-latency-high` | Azure Portal → SQL Database → Query Performance Insight → identificar query lenta. Cold start: aceitar. Contention: ver se Serverless precisa subir tier. |
| `mvp0-infobip-4xx` | Portal Infobip → verificar status dos templates + api key. Mensagem `last_error` em App Insights tem detalhe. |
| `mvp0-rate-limit-hits` | Avaliar: ataque (bloquear IP no WAF) ou tráfego legítimo crescendo (subir limite nos decorators `@limiter.limit(...)` em `app/api/{webhook,admin,dispatch}.py`). |
| `mvp0-pii-leak` | **URGENTE**: identificar log fonte via App Insights → adicionar `mask_pii()` no código → deploy hotfix → considerar rotacionar `LOG_PII_SALT` (invalida histórico mas necessário se vazamento confirmado). |

## Custos estimados

Alertas no Azure têm custo desprezível para volume do `mvp0`:

| Item | Custo aproximado |
|---|---|
| Action Group (emails) | Grátis até 1000 emails/mês |
| Metric alerts | ~R$ 0,50/regra/mês |
| Log search alerts (queries Kusto) | ~R$ 2,50/regra/mês |
| **Total dos 11 alertas acima** | **~R$ 25/mês** |

Comparar com o custo de **NÃO ter alertas**: 1 incidente não detectado por 24h pode causar dezenas de milhares em prejuízo (créditos Infobip drenados, parceiros não atendidos, suspensão do número WhatsApp).

## Atualização deste documento

Sempre que:

- Adicionar nova **fragilidade conhecida** → criar alerta correspondente
- Modificar **`log_dimensions.py`** → revisar queries Kusto que dependem dessas dimensões
- Mudar **threshold** após observar tráfego real → ajustar `--condition` + adicionar comentário com data e justificativa
- Adicionar **endpoint novo** → alertas de 4xx/5xx automáticos não detectam (são por URL específica) — criar regra dedicada
