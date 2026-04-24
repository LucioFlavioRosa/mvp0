from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.services.parceiros.match_service import MatchParceiroService

router = APIRouter()


@router.get("/match/{servico_id}", dependencies=[Depends(get_bff_token)])
async def match_parceiros(
    servico_id: int,
    lat: Optional[float] = Query(None, description="Latitude de referência"),
    lng: Optional[float] = Query(None, description="Longitude de referência"),
    db: Session = Depends(get_db),
):
    """
    Retorna parceiros aptos para um serviço, ordenados por proximidade.
    Aceita coordenadas opcionais para cálculo de distância real.
    """
    try:
        kwargs = {}
        if lat is not None:
            kwargs["lat_referencia"] = lat
        if lng is not None:
            kwargs["lng_referencia"] = lng
        return MatchParceiroService.match_parceiros(db, servico_id, **kwargs)
    except Exception as e:
        from fastapi import HTTPException
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar parceiros")
