# Auth Azure AD / Entra ID — Integração `/api/dispatch`

> Guia completo para configurar e integrar autenticação Azure AD no endpoint `POST /api/dispatch` do bot. Este documento serve **tanto para o time DevOps que provisiona** quanto **para o time do backoffice que vai consumir** o endpoint.

## Por que Azure AD aqui

O endpoint `/api/dispatch` dispara templates WhatsApp para parceiros — operação cara (créditos Infobip) e crítica (pode causar spam aos parceiros). Sem auth, qualquer um com a URL chama. Com Basic Auth, ninguém sabe **quem** disparou (auditoria impossível).

Com Azure AD:

- Operador faz login uma vez com email corporativo Aegea (SSO já existente)
- Cada chamada `/api/dispatch` carrega um JWT assinado pelo Azure AD com `oid` (object ID), `email`, `name`, `groups` do operador
- Backend valida o JWT (offline, usando chave pública do tenant — sem chamar Azure AD a cada request)
- Log estruturado registra **qual operador** disparou cada dispatch (LGPD friendly: `oid` opaco no log, email passa por `mask_pii`)
- Revogar acesso = desativar conta Azure AD do operador

## Arquitetura do fluxo

```
┌─────────────────────┐                                ┌─────────────────────┐
│   Operador          │   1. Login SSO Aegea           │   Azure AD          │
│   (browser)         │   ───────────────────────────► │   (Microsoft)       │
│                     │   ◄─────────────────────────── │                     │
│  Backoffice SPA     │   2. Retorna JWT (~1h validade)│                     │
│  (React/Angular/Vue)│                                └─────────────────────┘
│                     │
│  MSAL.js cacheia    │   3. POST /api/dispatch
│  token + renova     │      Authorization: Bearer eyJ0...
│                     │
└─────────────────────┘
          │
          ▼
┌──────────────────────────────────────┐         ┌─────────────────────┐
│   Bot Águas (FastAPI)                │         │   Azure AD          │
│                                      │         │   (chaves públicas) │
│  fastapi-azure-auth                  │ ──────► │                     │
│    - Cache chaves públicas (24h)     │ ◄────── │                     │
│    - Valida assinatura JWT offline   │         └─────────────────────┘
│    - Valida claims (aud/iss/exp/scp) │
│    - Injeta `user.claims` no endpoint│
│                                      │
│  /api/dispatch executa dispatch      │
│  e loga `operator_oid` + hash email  │
└──────────────────────────────────────┘
```

## Setup Azure AD (DevOps Aegea, uma vez por ambiente)

### Pré-requisitos

- Conta com role `Application Administrator` ou `Global Administrator` no tenant Azure AD da Aegea
- `tenant ID` da Aegea anotado (Portal Azure → Entra ID → Overview)

### Passo 1 — Registrar a App "Bot Águas API"

Esta é a "representação" do bot no Azure AD. Ela define qual scope o backoffice pode pedir.

1. Portal Azure → **Entra ID** → **App registrations** → **+ New registration**
2. Configurações:
   - **Name**: `Bot Aguas API` (dev/prod conforme ambiente — sugiro sufixo `-dev` e `-prod`)
   - **Supported account types**: `Accounts in this organizational directory only (Aegea only - Single tenant)`
   - **Redirect URI**: deixar em branco (essa app não loga ninguém, só expõe API)
3. Clicar **Register**
4. Anotar o **Application (client) ID** da página de Overview — vai virar o secret `AZURE-AD-API-CLIENT-ID`

### Passo 2 — Expor scope `dispatch.write` na "Bot Águas API"

1. Na app "Bot Aguas API" → **Expose an API**
2. Em **Application ID URI**: clicar "Set" → aceitar o default `api://<client-id>`
3. **+ Add a scope**:
   - **Scope name**: `dispatch.write`
   - **Who can consent?**: `Admins and users`
   - **Admin consent display name**: `Disparar oferta de servico a parceiros`
   - **Admin consent description**: `Permite chamar POST /api/dispatch para enviar templates WhatsApp aos parceiros via Infobip`
   - **User consent display name**: `Disparar ofertas a parceiros`
   - **User consent description**: `Permite que o backoffice dispare ofertas em seu nome`
   - **State**: `Enabled`
4. Clicar **Add scope**

### Passo 3 — Registrar a App "Bot Águas Backoffice"

Esta é a app cliente que vai obter tokens em nome dos operadores.

1. Portal Azure → **Entra ID** → **App registrations** → **+ New registration**
2. Configurações:
   - **Name**: `Bot Aguas Backoffice` (com sufixo `-dev`/`-prod`)
   - **Supported account types**: `Single tenant`
   - **Redirect URI**: tipo `Single-page application (SPA)`, URI `https://backoffice-aegea-prod.azurewebsites.net/callback` (ajustar conforme URL real)
3. Clicar **Register**
4. Anotar o **Application (client) ID** — vai pro código frontend (MSAL.js config)

### Passo 4 — Conceder permissão da "Backoffice" → "API"

1. Na app "Bot Aguas Backoffice" → **API permissions**
2. **+ Add a permission** → **My APIs** → selecionar "Bot Aguas API"
3. Tipo: **Delegated permissions** (acesso em nome do usuário logado)
4. Selecionar `dispatch.write` → **Add permissions**
5. Clicar **Grant admin consent for Aegea** (importante! sem isso operadores precisariam dar consent individual)

### Passo 5 — (Opcional mas recomendado) Restringir por grupo de operadores

Por padrão, qualquer membro do tenant Aegea pode obter o token. Pra restringir só a operadores autorizados:

1. **Entra ID** → **Groups** → **+ New group** → criar `bot-aguas-dispatch-operators`
2. Adicionar membros (operadores que podem chamar `/api/dispatch`)
3. Na app "Bot Aguas API" → **Enterprise applications** → encontrar a entry da "Bot Aguas Backoffice" → **Properties** → marcar **Assignment required = Yes**
4. **Users and groups** → **+ Add user/group** → adicionar o grupo `bot-aguas-dispatch-operators`

Agora só membros do grupo conseguem fazer login no backoffice **com permissão pro dispatch**. Outros operadores recebem erro.

### Passo 6 — Configurar secrets no Key Vault

```bash
KV_NAME=kv-aguasdopara-prod

az keyvault secret set --vault-name $KV_NAME \
  --name AZURE-AD-TENANT-ID \
  --value "<tenant-id-da-aegea>"

az keyvault secret set --vault-name $KV_NAME \
  --name AZURE-AD-API-CLIENT-ID \
  --value "<client-id-da-app-Bot-Aguas-API>"
```

> Esses valores não são "secretos" no sentido criptográfico — são identificadores públicos. Mas centralizar no Key Vault simplifica config e rotação.

### Passo 7 — Como o backend consome esses secrets

A configuração do scheme JWT acontece **no `lifespan` startup do FastAPI**, não no module-load do `app/core/azure_auth.py`. Fluxo:

1. `main.py` cria `app.state.settings = Settings()` (singleton Key Vault wrapper).
2. Dentro do `@asynccontextmanager` `lifespan`, antes do `yield`, chama `configure_azure_auth(app.state.settings)`.
3. `configure_azure_auth` lê `AZURE-AD-TENANT-ID` e `AZURE-AD-API-CLIENT-ID` do mesmo `Settings`, instancia o `SingleTenantAzureAuthorizationCodeBearer` e popula `_azure_scheme` no escopo do módulo.
4. `app/api/dispatch.py` declara `dependencies=[Depends(verify_dispatch_auth)]`. `verify_dispatch_auth` (em `app/api/deps.py`) chama `get_azure_scheme()` **a cada request** — sem cachear no escopo do módulo do router. Se o scheme ainda for `None` (secrets ausentes ou `configure_azure_auth` falhou), retorna 503 com `detail="dispatch auth not configured"` + log critical com `init_error`.

**Por que esse pattern (lazy-init via lifespan, não module-load):**

- O módulo `app/core/azure_auth.py` é importado por outros caminhos cedo no boot (via `app/api/deps.py` que importa o router). Se a inicialização rodasse no import, faria I/O Key Vault em cada boot de worker Gunicorn — N×4 leituras só pra subir o processo (4 workers × N instâncias).
- Lazy-init pelo lifespan move tudo pra uma única chamada por processo, depois do `Settings` singleton já estar populado em `app.state`.
- Se algum secret faltar, o app sobe (continua respondendo aos outros endpoints), e só `/api/dispatch` cai em 503 — isolamento de falha.

**Estado interno do módulo:**

| Símbolo | Significado |
|---|---|
| `_azure_scheme` | Instância do `SingleTenantAzureAuthorizationCodeBearer` ou `None` se ainda não configurado |
| `_init_error` | `str` com motivo da falha (ex: `"secrets ausentes: [...]"`) — usado pelo 503 detail |
| `configure_azure_auth(settings) -> bool` | Chamado no lifespan startup. Retorna `True` em sucesso, `False` em falha. |
| `get_azure_scheme()` | Retorna `_azure_scheme` (ou `None`). Lido dinamicamente pelo `verify_dispatch_auth`. |
| `get_init_error()` | Retorna `_init_error` (ou `None`). |

## Integração no frontend (time do backoffice)

### Instalar MSAL.js

```bash
npm install @azure/msal-browser
# Se usa React:
npm install @azure/msal-react
```

### Configurar MSAL

Arquivo `src/auth/msalConfig.ts` (ou equivalente):

```typescript
import { Configuration, PublicClientApplication } from "@azure/msal-browser";

export const msalConfig: Configuration = {
  auth: {
    clientId: "<client-id-da-app-Bot-Aguas-Backoffice>",
    authority: "https://login.microsoftonline.com/<tenant-id-da-aegea>",
    redirectUri: window.location.origin + "/callback",
    postLogoutRedirectUri: window.location.origin,
    navigateToLoginRequestUrl: true,
  },
  cache: {
    cacheLocation: "sessionStorage",  // ou "localStorage" se precisar persistir entre abas
    storeAuthStateInCookie: false,
  },
};

export const msalInstance = new PublicClientApplication(msalConfig);

// Scopes solicitados ao chamar /api/dispatch
export const dispatchScopes = {
  scopes: ["api://<client-id-da-app-Bot-Aguas-API>/dispatch.write"],
};
```

### Fluxo de login (uma vez por sessão)

```typescript
import { msalInstance } from "./msalConfig";

async function login() {
  const result = await msalInstance.loginPopup({
    scopes: ["openid", "profile", "email"],
  });
  // result.account contém info do operador
  msalInstance.setActiveAccount(result.account);
}
```

Ou para redirecionar (sem popup):

```typescript
await msalInstance.loginRedirect({
  scopes: ["openid", "profile", "email"],
});
```

### Função para chamar `/api/dispatch` com token

```typescript
import { msalInstance, dispatchScopes } from "./msalConfig";
import { InteractionRequiredAuthError } from "@azure/msal-browser";

interface DispatchPayload {
  pedido_uuid: string;
  parceiros: string[];
}

export async function dispararParaParceiros(payload: DispatchPayload) {
  const account = msalInstance.getActiveAccount();
  if (!account) {
    throw new Error("Operador não está autenticado. Faça login primeiro.");
  }

  let tokenResponse;
  try {
    // Tenta obter token do cache (silencioso, sem UI)
    tokenResponse = await msalInstance.acquireTokenSilent({
      ...dispatchScopes,
      account: account,
    });
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      // Token expirou e refresh falhou — pedir login de novo
      tokenResponse = await msalInstance.acquireTokenPopup(dispatchScopes);
    } else {
      throw error;
    }
  }

  // Chamada autenticada
  const response = await fetch(
    "https://app-aegea-prod-brazil.azurewebsites.net/api/dispatch",
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${tokenResponse.accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  );

  if (response.status === 401) {
    throw new Error("Não autorizado. Faça login novamente.");
  }
  if (response.status === 503) {
    throw new Error("Serviço indisponível. Contate DevOps.");
  }
  if (!response.ok) {
    throw new Error(`Dispatch falhou: ${response.statusText}`);
  }

  return await response.json();  // { status: "success", enviados: N }
}
```

### Exemplo de uso em componente React

```tsx
import { useState } from "react";
import { dispararParaParceiros } from "./dispatch";

export function DispatchButton({ pedidoUuid, parceiros }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setError(null);
    try {
      const result = await dispararParaParceiros({
        pedido_uuid: pedidoUuid,
        parceiros: parceiros,
      });
      alert(`${result.enviados} parceiros notificados`);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button onClick={handleClick} disabled={loading}>
        {loading ? "Disparando..." : "Disparar para parceiros"}
      </button>
      {error && <p style={{color: "red"}}>{error}</p>}
    </>
  );
}
```

## Configurar CORS no backend (Aegea DevOps)

Hoje o backend está com `allow_origins=["*"]` (item separado do roadmap). Quando o backoffice for deployado, apertar para a URL específica:

```python
# main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://backoffice-aegea-prod.azurewebsites.net",
        # adicionar dev/staging conforme necessário
    ],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

## Smoke test pós-deploy

```bash
APP_URL=https://app-aegea-prod-brazil.azurewebsites.net

# 1. Sem token deve dar 401
curl -i -X POST $APP_URL/api/dispatch \
  -H "Content-Type: application/json" \
  -d '{"pedido_uuid": "test", "parceiros": ["x"]}'
# Esperado: 401 Unauthorized

# 2. Com token bogus deve dar 401
curl -i -X POST $APP_URL/api/dispatch \
  -H "Authorization: Bearer fake.token.here" \
  -H "Content-Type: application/json" \
  -d '{"pedido_uuid": "test", "parceiros": ["x"]}'
# Esperado: 401 (assinatura JWT invalida)

# 3. Se secrets AZURE-AD-* nao configurados no Key Vault: 503
# (configurar antes do go-live - ver passo 6 acima)
```

## Troubleshooting

### Frontend: `InteractionRequiredAuthError` ao chamar `acquireTokenSilent`

Token cache expirou OU sessão SSO foi invalidada. Solução: chamar `acquireTokenPopup` ou `acquireTokenRedirect` que abre fluxo interativo.

### Frontend: `consent_required`

Admin consent não foi concedido (passo 4). DevOps precisa clicar **Grant admin consent for Aegea** no portal.

### Backend: 401 mesmo com token válido

Verificar claims do token em [jwt.ms](https://jwt.ms):

- `aud` deve ser `api://<client-id-da-Bot-Aguas-API>` (não o ID do backoffice)
- `iss` deve apontar pro tenant Aegea
- `scp` deve incluir `dispatch.write`
- `exp` ainda no futuro

Se `aud` está errado, o backoffice está pedindo token para a API errada. Conferir `dispatchScopes` na config.

### Backend: 503 `dispatch auth not configured`

Secrets `AZURE-AD-TENANT-ID` ou `AZURE-AD-API-CLIENT-ID` ausentes no Key Vault. Conferir passo 6.

### Backend: HTTP 500 ao validar token

Provavelmente Managed Identity sem permissão para ler secrets do Key Vault. Conferir Role Assignment do passo 3 do `DEPLOYMENT.md`.

## Anatomia do JWT recebido

Para debug, decode no [jwt.ms](https://jwt.ms) (não envia o token a lugar nenhum — é JavaScript local). Claims relevantes:

| Claim | Significado |
|---|---|
| `aud` | Audience: pra qual API o token foi emitido |
| `iss` | Issuer: tenant Azure AD que assinou |
| `exp` | Expiration: timestamp unix |
| `oid` | Object ID: identidade única do operador (não muda mesmo se ele trocar email) |
| `preferred_username` ou `email` | Email do operador |
| `name` | Nome do operador |
| `scp` | Scopes concedidos (deve conter `dispatch.write`) |
| `groups` | IDs dos grupos do operador (se passo 5 configurado) |
| `roles` | App roles atribuídos (não usamos aqui) |

## Resumo das credenciais

| Tipo | Quem armazena | Onde |
|---|---|---|
| **Tenant ID** | DevOps Aegea | Key Vault (`AZURE-AD-TENANT-ID`) + config MSAL.js do backoffice |
| **API Client ID** ("Bot Aguas API") | DevOps Aegea | Key Vault (`AZURE-AD-API-CLIENT-ID`) + config MSAL.js (escopo) |
| **Backoffice Client ID** ("Bot Aguas Backoffice") | Time backoffice | Config MSAL.js (clientId) |
| **Senha do operador** | Operador (sabe), Azure AD (verifica) | NUNCA chega no backoffice nem no bot |
| **JWT (access token)** | Browser do operador | sessionStorage (MSAL cache), header `Authorization` |

Nenhuma senha viaja para o bot. Operador troca senha no Azure AD → próximo token continua funcionando sem nenhuma mudança em código.
