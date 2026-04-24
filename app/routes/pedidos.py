from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
import traceback

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.schemas.pedido import PedidosListResponse
from app.services.pedidos.pedido_service import PedidoService # Import ajustado

router = APIRouter()

@router.get("", response_model=PedidosListResponse, dependencies=[Depends(get_bff_token)])
async def list_pedidos(
    status: Optional[str] = Query(None, description="Filtrar por Status"),
    urgencia: Optional[str] = Query(None, description="Filtrar por Urgência"),
    unidade: Optional[str] = Query(None, description="Filtrar por Nome da Unidade"),
    tipo_servico: Optional[str] = Query(None, description="Filtrar por Nome do Serviço"),
    bloco: Optional[str] = Query(None, description="Filtrar por Bloco"),
    db: Session = Depends(get_db)
):
    """
    Retorna a lista de pedidos filtrados e formatados para consumo do BFF.
    Exige autenticação via header X-BFF-Token.
    """
    try:
        resultado = PedidoService.get_pedidos(
            db=db,
            status=status,
            urgencia=urgencia,
            unidade_nome=unidade,
            tipo_servico_nome=tipo_servico,
            bloco=bloco
        )
        return resultado
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)} 

@router.get("/{pedido_id}", dependencies=[Depends(get_bff_token)])
async def get_pedido_detalhes(
    pedido_id: str,
    db: Session = Depends(get_db)
):
    """
    Retorna os detalhes de um pedido específico, junto com a lista
    de parceiros qualificados (calculada a distância via geopy e formatada).
    """
    from fastapi import HTTPException
    try:
        resultado = PedidoService.obter_pedido_detalhado(db, pedido_id)
        if not resultado:
            raise HTTPException(status_code=404, detail="Pedido não encontrado")
        return resultado
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro interno ao buscar pedido")

from app.schemas.pedido import DesvincularRequest, PedidoCreateRequest, PedidoUpdateRequest

@router.post("", dependencies=[Depends(get_bff_token)])
async def criar_pedido(
    data: PedidoCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Cria uma nova Ordem de Serviço no Backend.
    """
    from fastapi import HTTPException
    novo_pedido = PedidoService.criar_pedido(db, data)
    if not novo_pedido:
        raise HTTPException(status_code=400, detail="Erro ao criar a Ordem de Serviço.")
    return {"success": True, "PedidoID": novo_pedido.PedidoID}

@router.patch("/{pedido_id}", dependencies=[Depends(get_bff_token)])
async def editar_pedido(
    pedido_id: str,
    data: PedidoUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Atualiza campos específicos de uma Ordem de Serviço (PATCH).
    """
    from fastapi import HTTPException
    pedido_atualizado = PedidoService.atualizar_pedido(db, pedido_id, data)
    if not pedido_atualizado:
        raise HTTPException(status_code=404, detail="Pedido não encontrado ou erro na atualização.")
    return {"success": True, "message": "Pedido atualizado com sucesso"}

@router.post("/{pedido_id}/desvincular", dependencies=[Depends(get_bff_token)])
async def desvincular_pedido(
    pedido_id: str,
    data: DesvincularRequest,
    db: Session = Depends(get_db)
):
    """
    Desvincula o parceiro alocado de um pedido e volta seu status para AGUARDANDO.
    """
    from fastapi import HTTPException
    try:
        sucesso = PedidoService.desvincular_parceiro(db, pedido_id, data.mensagem)
        if not sucesso:
            raise HTTPException(status_code=400, detail="Não foi possível desvincular o parceiro deste pedido.")
        return {"success": True, "message": "Parceiro desvinculado com sucesso"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro interno ao desvincular parceiro")
