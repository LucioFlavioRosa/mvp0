from fastapi import APIRouter, Depends, Query, HTTPException
import traceback
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.services.parceiros.match_service import MatchParceiroService
from app.services.parceiros.parceiro_service import ParceiroService
from app.schemas.parceiro import (
    ListarParceirosResponse,
    DetalheParceiroResponse,
    ParceirosComOSResponse
)

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
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar parceiros")

@router.get("", dependencies=[Depends(get_bff_token)], response_model=ListarParceirosResponse)
async def listar_parceiros(
    status: Optional[str] = Query(None),
    cidade: Optional[str] = Query(None),
    nome: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Retorna a lista de parceiros de acordo com os filtros solicitados.
    """
    try:
        filtros = {
            "status": status,
            "cidade": cidade,
            "nome": nome
        }
        # Limpar Nones
        filtros = {k: v for k, v in filtros.items() if v}
        
        return ParceiroService.listar_parceiros(db, filtros)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao listar parceiros")

@router.get("/vinculados/os", dependencies=[Depends(get_bff_token)], response_model=ParceirosComOSResponse)
async def parceiros_com_os(
    db: Session = Depends(get_db)
):
    """
    Retorna parceiros e suas ordens de serviço vinculadas.
    """
    try:
        return ParceiroService.parceiros_com_os(db)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar parceiros com OS")

@router.get("/{parceiro_uuid}", dependencies=[Depends(get_bff_token)], response_model=DetalheParceiroResponse)
async def obter_parceiro_detalhe(
    parceiro_uuid: str,
    db: Session = Depends(get_db)
):
    """
    Retorna o perfil completo de um parceiro (Dados Pessoais, Habilidades, Disponibilidade, Histórico).
    """
    try:
        resultado = ParceiroService.obter_detalhes_parceiro(db, parceiro_uuid)
        if not resultado:
            raise HTTPException(status_code=404, detail="Parceiro não encontrado")
        return resultado
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar detalhes do parceiro")

