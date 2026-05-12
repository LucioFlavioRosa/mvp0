# Documento de Referência de Arquitetura (ARD)
## Plataforma de Gestão de Parceiros via WhatsApp (Peers CodeAI / Aegea)

| Metadado | Detalhe |
| :--- | :--- |
| **Status** | `Em Revisão - Comitê de Segurança` |
| **Data** | `01/02/2026` |
| **Classificação** | `Confidencial` |
| **Autor** | Equipe de Arquitetura |
| **Stakeholders** | Operações, Segurança da Informação, Engenharia |

---

## 1. Resumo Executivo

Esta solução visa orquestrar o ciclo de vida de prestadores de serviço terceiros (Parceiros) para a Aegea/Eurofarma, desde o *onboarding* e validação documental até a execução de ordens de serviço e pagamentos. A interface principal de interação é via **WhatsApp (Twilio)**, suportada por uma arquitetura *Cloud-Native* no Azure.

Este documento detalha a topologia da infraestrutura, o modelo de dados e, principalmente, os controles de segurança aplicados para garantir conformidade com a LGPD e as políticas de InfoSec corporativas.

---

## 2. Diagrama de Infraestrutura & Segurança

A arquitetura segue o padrão de **Segurança em Camadas (Defense in Depth)**, utilizando serviços PaaS gerenciados para reduzir a superfície de ataque e segregar redes públicas de privadas.

```mermaid
flowchart TB
 subgraph G1["1. Experiência & Segurança de Borda (Zero Trust)"]
   direction TB
    USER@{ label: "Parceiro<br>(WhatsApp/Web)" }
    AFD["Azure Front Door<br>(WAF Premium + DDoS Protection)"]
    SWA["Frontend Admin<br>(Azure Static Web Apps)"]
 end
 subgraph G2["2. Backend & Orquestração (Private VNET)"]
   direction TB
    APS["API Backend<br>(App Service - Linux)"]
    AFN["Azure Functions<br>(Processamento Async)"]
    SB["Service Bus<br>(Desacoplamento)"]
 end
 subgraph G3["3. Dados & Governança (Data Plane)"]
   direction TB
    SQL["SQL Azure<br>(TDE Enabled)"]
    REDIS["Redis Cache<br>(Sessão Chat)"]
    BLOB["Blob Storage<br>(Docs Criptografados)"]
    KV["Azure Key Vault<br>(Gestão de Segredos)"]
 end
 subgraph G4["4. Integrações Corporativas"]
   direction TB
    TW@{ label: "Twilio (Webhook Seguro)" }
    IDW@{ label: "IdP / Legacy Identity" }
    ORA@{ label: "Oracle (ERP)" }
    SAP@{ label: "SAP (Financeiro)" }
 end
 subgraph OPS["Operação & Observabilidade"]
   direction TB
    ADO["Azure DevOps<br>(CI/CD Seguro)"]
    AI["App Insights<br>(Audit Logs & Tracing)"]
 end
    USER -- HTTPS/TLS 1.2 --> AFD
    AFD -- Private Link --> SWA
    SWA -- Managed Identity --> APS
    APS -- Managed Identity --> AFN & SB & SQL & REDIS & KV & TW
    AFN -- Private Endpoints --> BLOB & IDW
    SB -- Async/Retry Pattern --> SAP & ORA
    ADO -.-> SWA
    APS -.-> AI
    AFN -.-> AI
    SQL -.-> AI

    AFD@{ icon: "azure:front-door-and-cdn-profiles", form: "square"}
    SWA@{ icon: "azure:static-apps", form: "square"}
    APS@{ icon: "azure:app-services", form: "square"}
    AFN@{ icon: "azure:function-apps", form: "square"}
    SB@{ icon: "azure:azure-service-bus", form: "square"}
    SQL@{ icon: "azure:sql-server", form: "square"}
    REDIS@{ icon: "azure:cache-redis", form: "square"}
    BLOB@{ icon: "azure:storage-accounts", form: "square"}
    KV@{ icon: "azure:key-vaults", form: "square"}
    ADO@{ icon: "azure:azure-devops", form: "square"}
    AI@{ icon: "azure:application-insights", form: "square"}
    
    classDef area fill:#f9f9f9,stroke:#666,stroke-width:1px,stroke-dasharray: 0
    classDef external fill:#e3f2fd,stroke:#1565c0,stroke-width:1px,stroke-dasharray: 5 5
```

### 2.1 Detalhamento dos Controles de Segurança

| Camada | Componente | Controle de Segurança Implementado |
| :--- | :--- | :--- |
| **Borda** | **Azure Front Door** | Atua como WAF (Web Application Firewall) bloqueando OWASP Top 10, SQL Injection e XSS. Terminação TLS/SSL forçada. |
| **Computação** | **App Service / Functions** | Uso estrito de **Managed Identities** para eliminar credenciais hardcoded no código. Isolamento via Integração VNET (Subnet Delegation). |
| **Dados** | **SQL Azure** | Criptografia em repouso (TDE), Firewall lógico (Allow Azure Services only ou Private Endpoint) e Auditoria de Acesso ativada. |
| **Segredos** | **Key Vault** | Centraliza chaves de API (Twilio), Strings de Conexão legado e Certificados. Nenhuma chave reside no repositório de código (Git). |
| **Armazenamento**| **Blob Storage** | Armazena documentos (CNH/Selfie). Acesso via SAS Token de curta duração e expiração automática. Criptografia AES-256. |

---

## 3. Modelo de Dados e Privacidade (LGPD)

O diagrama abaixo ilustra a estrutura de dados relacional. Atenção especial foi dada à segregação de dados sensíveis (PII) e logs de interação, bem como a nova estrutura de `PEDIDOS_DISPAROS` para rastreio de ofertas ativas.

```mermaid
erDiagram
    direction BT

    %% ========================================================
    %% TABELAS PRINCIPAIS (Resumo)
    %% ========================================================
    CHAT_SESSIONS {
        VARCHAR WhatsAppID PK "Anonimizado em Logs"  
        VARCHAR CurrentStep  "Estado da Máquina"  
        NVARCHAR TempData  "TTL Curto (Redis/Mem)"  
        DATETIME LastUpdate  "Timeout Control"  
    }

    PARCEIROS_PERFIL {
        GUID ParceiroUUID PK "Identidade Única"  
        VARCHAR WhatsAppID  "Dado Sensível"  
        VARCHAR CNPJ  "Dado Público"  
        VARCHAR CPF  "PII - Sensível (LGPD)"  
        VARCHAR NomeCompleto  "PII"  
        VARCHAR Email "PII"
        ENUM StatusAtual  "Governance State"  
        GEOGRAPHY Geo_Base  "Dado Sensível (Rastreio)"  
        VARCHAR chave_pix  "Dado Financeiro"  
        BOOL Aceite  "Consentimento LGPD"  
    }

    PARCEIROS_DOCS_LEGAIS {
        INT DocID PK "IDENTITY"  
        GUID ParceiroUUID FK ""  
        ENUM TipoDocumento  "CNH, SELFIE (Biometria)"  
        VARCHAR BlobPath  "Private Container"  
        ENUM StatusValidacao "Audit Trail"
    }

    PEDIDOS_SERVICO {
        GUID PedidoID PK "Default NEWID()"
        VARCHAR CEP ""
        VARCHAR Rua ""
        VARCHAR Numero ""
        FLOAT Valor "Dado de Negócio"
        VARCHAR StatusPedido "AGUARDANDO, VINCULADO..."
    }

    PEDIDOS_DISPAROS {
        BIGINT DisparoID PK "IDENTITY"
        GUID PedidoID FK "Link com Pedido"
        GUID ParceiroUUID FK "Link com Parceiro"
        VARCHAR Status "ENVIADO, ACEITO, NEGADO..."
        DATETIME DataAtualizacao "Log de Auditoria"
    }

    ORDENS_SERVICO {
        GUID OrdemID PK "" 
        GUID PedidoID FK ""
        GUID ParceiroAlocadoUUID FK "" 
        ENUM StatusOrdem  "ABERTA, EM_EXECUCAO, CONCLUIDA" 
    }

    INTERACOES_CHAT {
        BIGINT ChatID PK "IDENTITY"  
        GUID ParceiroUUID FK ""  
        NVARCHAR CorpoMensagem  "Audit Trail"  
        DATETIME DataHora  ""  
    }

    %% ========================================================
    %% RELACIONAMENTOS DE SEGURANÇA E NEGÓCIO
    %% ========================================================
    PARCEIROS_PERFIL ||--o{ PARCEIROS_DOCS_LEGAIS : "Upload Seguro"
    PARCEIROS_PERFIL ||--o{ INTERACOES_CHAT : "Gera Logs"
    PARCEIROS_PERFIL ||--o{ ORDENS_SERVICO : "Executa"
    PARCEIROS_PERFIL ||--o{ PEDIDOS_DISPAROS : "Recebe Oferta"
    
    PEDIDOS_SERVICO ||--o{ ORDENS_SERVICO : "Origina"
    PEDIDOS_SERVICO ||--o{ PEDIDOS_DISPAROS : "Gera Oferta"
    
    ORDENS_SERVICO ||--o{ INTERACOES_CHAT : "Contexto"
```

### 3.1 Inventário de Dados Sensíveis e Proteção

A tabela abaixo mapeia os dados críticos identificados no ER Diagram e sua estratégia de proteção:

| Entidade | Dado | Classificação | Estratégia de Proteção |
| :--- | :--- | :--- | :--- |
| **Parceiros** | CPF / Email / Tel | **PII (LGPD)** | Acesso restrito via RBAC na aplicação. Mascaramento em logs de aplicação. |
| **Parceiros** | Selfie / CNH | **Biometria** | Armazenamento em Blob "Hot" Privado no Azure Storage. Acesso apenas via aplicação (Backend Proxy com SAS Token). |
| **Parceiros** | Chave Pix | **Financeiro** | Criptografia a nível de coluna (Always Encrypted) ou restrição severa de visualização via API. |
| **Chat** | Mensagens | **Comunicação** | Retenção definida (ex: 5 anos para fins legais), após isso, expurgo automático (Data Retention Policy). |

---

## 4. Fluxos de Integração e Segurança de Rede

### 4.1 Integração com WhatsApp (Infobip)
Para garantir que apenas o Infobip possa invocar nossos Webhooks e evitar ataques de *Replay* ou *Man-in-the-Middle*:
1.  **Basic Auth no Webhook:** No portal Infobip, o perfil de segurança Basic Auth é vinculado ao evento `INBOUND_MESSAGE` e à URL de roteamento `/bot`. No backend, a dependência FastAPI `verify_infobip_basic_auth` (em `main.py`) lê `INFOBIP-WEBHOOK-USER` e `INFOBIP-WEBHOOK-PASSWORD` do **Azure Key Vault** e valida cada requisição com `secrets.compare_digest` (constant-time, resistente a timing attacks). Fail-safe: retorna 503 se as credenciais não estão configuradas, 401 se inválidas.
2.  **HTTPS:** Todo tráfego é criptografado em trânsito (TLS 1.2+).
3.  **Histórico:** A integração anterior (Twilio) usava validação de assinatura via header `X-Twilio-Signature`. Substituída por Basic Auth na migração Twilio→Infobip + implementação no PR `feat/webhook-basic-auth`.

### 4.2 Integração com Legado (SAP/Oracle/IDW)
A comunicação com os sistemas *on-premise* ou legados não é exposta à internet pública.
1.  **Isolamento:** Utilização de **VNET Integration** nas Azure Functions e App Service.
2.  **Conectividade:** Tráfego roteado via VPN Gateway ou ExpressRoute.
3.  **Credenciais:** Credenciais de banco de dados legados são injetadas em tempo de execução via Key Vault References (o desenvolvedor não vê a senha).

---

## 5. Auditoria e Observabilidade

Todas as ações críticas são auditadas para fins forenses e de conformidade:

* **Application Insights:** Coleta logs de aplicação (Payloads sensíveis são sanitizados antes do log), métricas de performance e falhas.
* **Azure Monitor:** Monitora a saúde e disponibilidade dos recursos PaaS.
* **Log de Auditoria de Banco:** O SQL Azure mantém logs de auditoria sobre quem acessou quais tabelas (Query Store / Audit Logs).
* **Trilha de Aceite:** O campo `Aceite` na tabela `PARCEIROS_PERFIL` armazena o timestamp e versão dos termos de uso aceitos pelo usuário (Requisito Jurídico irrevogável).

---

### 5.1 Telemetria Estruturada (Application Insights)

A aplicação envia telemetria estruturada para o **Azure Application Insights** via biblioteca `azure-monitor-opentelemetry`. Configuração consolidada em `app/core/telemetry.py`. Pontos relevantes para Segurança e Governança:

| Aspecto | Implementação |
| :--- | :--- |
| **Auto-instrumentação** | FastAPI (requests inbound), `requests`/`httpx` (HTTP outbound) e `pyodbc` (SQL) instrumentados sem código manual. Captura `requestTelemetry`, `dependencyTelemetry` e `exceptionTelemetry` automaticamente. |
| **Custom Dimensions canônicas** | Vocabulário central em `app/core/log_dimensions.py` (`operation`, `step`, `sender_hash`, `external_service`, `duration_ms`, etc) — viabiliza queries Kusto consistentes. |
| **Mascaramento de PII (LGPD)** | Função `mask_pii(value)` aplica SHA-256 truncado (12 chars) com salt rotacionável via env var `LOG_PII_SALT`. Determinístico — permite correlação por usuário sem reidentificação. Aplicado a WhatsApp ID, CPF, CNPJ, e-mail em todos os logs estruturados. |
| **Correlation ID** | Middleware FastAPI atribui `operation_id` por request (header `X-Operation-Id` propagado). Injetado em todas as `customDimensions` via `logging.Filter` — permite query "todos os logs deste webhook". |
| **Níveis de log** | `LOG_LEVEL` em env var. Default `INFO` em produção. `DEBUG` apenas em investigação temporária. |
| **Conexão** | `APPLICATIONINSIGHTS_CONNECTION_STRING` configurada em App Service Settings (não vai pro código). |

#### Garantias adicionais para LGPD

- Logs de inbound (`webhook_inbound`) **nunca** contêm o conteúdo da mensagem do usuário — apenas `message_type` e `message_len`.
- Coordenadas GPS de parceiros vão para nível **DEBUG** (não persiste em produção).
- Query de sanity check (regex CPF/CNPJ em `traces.message`) executada após cada release detecta vazamentos acidentais — se retornar resultados, abrir incidente.

---

## 6. Conclusão para o Comitê

A arquitetura proposta utiliza serviços gerenciados (Serverless/PaaS) para minimizar a sobrecarga operacional de patches de segurança e maximizar a disponibilidade. O uso de **Managed Identities** e **Key Vault** garante o princípio de privilégio mínimo e a proteção de segredos. A estrutura de dados foi desenhada considerando a segregação lógica necessária para atender à LGPD, com controles de acesso, criptografia e auditoria nativos da nuvem Azure.
