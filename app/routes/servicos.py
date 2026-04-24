from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.services.servicos.servico_service import ServicoService

router = APIRouter()


@router.get("", dependencies=[Depends(get_bff_token)])
async def list_servicos(db: Session = Depends(get_db)):
    """
    Retorna o catálogo geral de todos os serviços cadastrados.
    """
    try:
        return ServicoService.listar_geral(db)
    except Exception as e:
        from fastapi import HTTPException
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar catálogo de serviços")
