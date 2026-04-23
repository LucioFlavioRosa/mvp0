from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
import traceback

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.schemas.pedido import PedidosListResponse
from app.services.pedido_service import PedidoService

router = APIRouter()

@router.get("/", response_model=PedidosListResponse)
async def list_pedidos(
    status: Optional[str] = Query(None, description="Filtrar por Status"),
    urgencia: Optional[str] = Query(None, description="Filtrar por Urgência"),
    unidade: Optional[str] = Query(None, description="Filtrar por Nome da Unidade"),
    tipo_servico: Optional[str] = Query(None, description="Filtrar por Nome do Serviço"),
    bloco: Optional[str] = Query(None, description="Filtrar por Bloco"),
    db: Session = Depends(get_db),
    token: str = Depends(get_bff_token) # Trava de segurança
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
        return {"error": str(e)} # Em produção, usar HTTPException
