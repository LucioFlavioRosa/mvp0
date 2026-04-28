"""
Routes — Domínio: Materiais
Prefixo: /api/materiais

Endpoints:
  GET /api/materiais → listagem completa do catálogo de materiais
"""

import traceback

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.services.servicos.servico_service import ServicoService

router = APIRouter()


@router.get("", dependencies=[Depends(get_bff_token)])
def listar_materiais(db: Session = Depends(get_db)):
    """Retorna todos os materiais do catálogo."""
    try:
        return ServicoService.listar_materiais(db)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar materiais.")
