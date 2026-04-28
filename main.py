from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

# Core e Segurança
from app.core.auth import get_bff_token

# Rotas Limpas
from app.routes import pedidos as route_pedidos
from app.routes import chatbot as route_chatbot
from app.routes import unidades as route_unidades
from app.routes import servicos as route_servicos
from app.routes import materiais as route_materiais
from app.routes import parceiros as route_parceiros
from app.routes import backoffice as route_backoffice
from app.routes import agrupamentos as route_agrupamentos
from app.routes import estrutural as route_estrutural

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
app.include_router(route_pedidos.router, prefix="/api/pedidos", tags=["Pedidos"])

# Rotas do Chatbot -> Contém o Webhook (/bot) e APIs de Integração com o WhatsApp
app.include_router(route_chatbot.router)

# Rotas Estruturais -> Unidades com serviços ativos
app.include_router(route_unidades.router, prefix="/api/unidades", tags=["Unidades"])

# Rotas de Serviços -> Catálogo geral
app.include_router(route_servicos.router, prefix="/api/servicos", tags=["Serviços"])

# Rotas de Parceiros -> Match de parceiros aptos
app.include_router(route_parceiros.router, prefix="/api/parceiros", tags=["Parceiros"])

# Rotas de Backoffice -> KPIs, métricas e verificação de cobertura
app.include_router(route_backoffice.router, prefix="/api/backoffice", tags=["Backoffice"])

# Rotas de Agrupamentos -> Match coletivo e disparo em lote
app.include_router(route_agrupamentos.router, prefix="/api/agrupamentos", tags=["Agrupamentos"])

# Rotas Estruturais Admin -> CRUD de Empresas, Filiais e Unidades
app.include_router(route_estrutural.router, prefix="/api/estrutural", tags=["Estrutural"])

# Rotas de Materiais -> Catálogo de materiais
app.include_router(route_materiais.router, prefix="/api/materiais", tags=["Materiais"])
