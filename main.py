from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

# Core e Segurança
from app.core.auth import get_bff_token

# Rotas Limpas
from app.routes import pedidos as route_pedidos
from app.routes import chatbot as route_chatbot

# ==============================================================================
# 1. INICIALIZAÇÃO
# ==============================================================================

app = FastAPI(title="Aegea Backend Unificado", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# 2. ROTAS DE SAÚDE (HEALTH CHECKS)
# ==============================================================================

@app.get("/", tags=["Health"])
def health_check():
    """Rota raiz simples para ping de infraestrutura (Azure)."""
    return {"status": "online", "application": "Aegea Chatbot & API"}

@app.get("/api/health", dependencies=[Depends(get_bff_token)], tags=["Health"])
async def protected_health_check():
    """Validação de comunicação com o BFF via token."""
    return {"status": "secure_online", "message": "Backend unificado respondendo."}

# ==============================================================================
# 3. MONTAGEM DAS ROTAS GERAIS
# ==============================================================================

# Rota de Pedidos -> Acessível via /api/pedidos (Padrão simples e direto)
app.include_router(route_pedidos.router, tags=["Pedidos"])

# Rotas do Chatbot -> Contém o Webhook (/bot) e APIs de Integração com o WhatsApp
app.include_router(route_chatbot.router)
