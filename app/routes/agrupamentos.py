"""
Routes — Domínio: Agrupamentos de OS (Lote)
Prefixo: /api/agrupamentos

Expõe os endpoints de match coletivo e disparo em lote para o BFF (Portal Aegea).
Todos os endpoints exigem autenticação via header X-BFF-Token.
"""

import traceback
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.schemas.agrupamento import (
    AgrupamentoDetalhesResponse,
    DisparoLoteRequest,
    DisparoLoteResponse,
)
from app.services.pedidos.agrupamento_service import AgrupamentoService

router = APIRouter()


# ============================================================================
# GET /api/agrupamentos/detalhes
# Retorna pedidos formatados e parceiros compatíveis com o lote.
# Equivale ao endpoint legado GET /agrupamentos/detalhes consumido pelo Portal.
# ============================================================================

@router.get("/detalhes", response_model=AgrupamentoDetalhesResponse, dependencies=[Depends(get_bff_token)])
async def detalhes_agrupamento(
    id_pedidos: List[str] = Query(..., description="Lista de UUIDs dos pedidos a agrupar"),
    db: Session = Depends(get_db),
):
    """
    Valida os pedidos, executa o match coletivo de parceiros (having count)
    e retorna os dados estruturados com centroide e distâncias calculadas.
    """
    if not id_pedidos or len(id_pedidos) == 0 or len(id_pedidos) > 10:
        raise HTTPException(status_code=400, detail="Quantidade de OS inválida. Mínimo 2, máximo 10.")

    try:
        resultado = AgrupamentoService.obter_detalhes_lote(db, id_pedidos)

        if resultado.get("error"):
            raise HTTPException(status_code=422, detail=resultado["error"])

        return resultado
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro interno ao buscar detalhes do agrupamento.")


# ============================================================================
# POST /api/agrupamentos/enviar-requisicao
# Dispara WhatsApp em lote para múltiplos pedidos e parceiros.
# Equivale ao endpoint legado POST /agrupamento/enviar-requisicao do Portal.
# ============================================================================

@router.post("/enviar-requisicao", response_model=DisparoLoteResponse, dependencies=[Depends(get_bff_token)])
async def enviar_requisicao_lote(
    data: DisparoLoteRequest,
    db: Session = Depends(get_db),
):
    """
    Dispara convites WhatsApp para os parceiros selecionados em cada OS do lote.
    Registra auditoria via DispatchService. Aguarda 0.5s entre pedidos.
    """
    if not data.id_pedidos:
        raise HTTPException(status_code=400, detail="Quantidade insuficiente de OS.")

    if not data.parceiros_selecionados:
        raise HTTPException(status_code=400, detail="Nenhum parceiro selecionado.")

    try:
        resultado = await AgrupamentoService.disparar_lote(
            db, data.id_pedidos, data.parceiros_selecionados
        )
        return resultado
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro interno ao processar disparo em lote.")
