# app/core/auth.py
from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from app.core.config import Settings

# Instância de configurações para buscar o segredo do ambiente/KV
settings = Settings()

# Nome do header que o BFF deve enviar
API_KEY_NAME = "X-BFF-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_bff_token(api_key: str = Security(api_key_header)):
    """
    Dependência para proteger as rotas do Backend.
    Verifica se o token enviado no header 'X-BFF-Token' coincide com o segredo do servidor.
    """
    expected_token = settings.get_secret("BFF_API_TOKEN")
    
    if not expected_token:
        # Erro crítico de configuração no servidor
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuração de segurança incompleta: BFF_API_TOKEN ausente no servidor."
        )
        
    if api_key == expected_token:
        return api_key
        
    # Se o token não bater ou estiver ausente
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Acesso negado: Token de serviço (X-BFF-Token) inválido ou ausente."
    )
