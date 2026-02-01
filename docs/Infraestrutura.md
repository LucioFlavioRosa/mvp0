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
