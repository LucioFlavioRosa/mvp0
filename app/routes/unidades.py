from fastapi import APIRouter, Depends, HTTPException
import traceback
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.services.unidades.unidade_service import UnidadeService

router = APIRouter()


@router.get("", dependencies=[Depends(get_bff_token)])
async def list_unidades(db: Session = Depends(get_db)):
    """
    Retorna todas as unidades cadastradas (id e nome).
    Utilizado para popular o primeiro select do formulário de Nova OS.
    """
    try:
        return UnidadeService.listar_todas(db)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar unidades")


@router.get("/{unidade_id}/servicos", dependencies=[Depends(get_bff_token)])
async def list_servicos_unidade(unidade_id: int, db: Session = Depends(get_db)):
    """
    Retorna os serviços ativos e preços de uma unidade específica.
    Utilizado pela cascata do formulário após seleção de unidade.
    """
    try:
        return UnidadeService.listar_servicos_unidade(db, unidade_id)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar serviços da unidade")
