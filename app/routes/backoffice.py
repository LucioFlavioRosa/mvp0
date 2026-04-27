"""
Routes — Domínio: Backoffice & Métricas
Prefixo: /api/backoffice

Expõe os endpoints de KPIs e cobertura geográfica para consumo do BFF (Portal Aegea).
Todos os endpoints exigem autenticação via header X-BFF-Token.
"""

import traceback
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.schemas.backoffice import DashboardResponse, CoberturaRequest, CoberturaResponse
from app.services.backoffice.backoffice_service import BackofficeService

router = APIRouter()


# ============================================================================
# GET /api/backoffice
# Retorna o dashboard completo: KPIs de conversão, balanço e totalizadores.
# Equivale ao endpoint legado GET /backoffice consumido pelo Portal.
# ============================================================================

@router.get("", response_model=DashboardResponse, dependencies=[Depends(get_bff_token)])
async def obter_dashboard(db: Session = Depends(get_db)):
    """
    Dashboard de Backoffice com métricas consolidadas de conversão e
    balanço demanda vs oferta. Totalizadores calculados no Backend.
    """
    try:
        return BackofficeService.obter_dashboard(db)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro interno ao gerar dashboard de backoffice.")


# ============================================================================
# POST /api/backoffice/cobertura
# Recebe um endereço textual e retorna a cobertura de parceiros aptos.
# Equivale ao endpoint legado POST /api/cobertura consumido pelo Portal.
# ============================================================================

@router.post("/cobertura", response_model=CoberturaResponse, dependencies=[Depends(get_bff_token)])
async def verificar_cobertura(payload: CoberturaRequest, db: Session = Depends(get_db)):
    """
    Verifica cobertura de parceiros ativos para um endereço informado.
    Geocodifica o endereço e faz query espacial usando STDistance (SQL Server Geography).
    """
    try:
        resultado = BackofficeService.verificar_cobertura(db, payload.endereco)

        if resultado.get("error"):
            raise HTTPException(status_code=422, detail=resultado["error"])

        return resultado
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro interno ao verificar cobertura.")
