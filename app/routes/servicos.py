"""
Routes — Domínio: Catálogo de Serviços & Materiais
Prefixo: /api/servicos

Endpoints:
  GET  /api/servicos              → catálogo completo
  POST /api/servicos/catalogo     → criar serviço
  PUT  /api/servicos/catalogo/{id} → editar serviço
  GET  /api/servicos/unidades     → unidades com serviços configurados
  POST /api/servicos/vincular     → upsert de preço por unidade
"""

import traceback

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.services.servicos.servico_service import ServicoService
from app.schemas.servico import ServicoCreate, ServicoUpdate, VincularServicoUnidade

router = APIRouter()


# ============================================================================
# CATÁLOGO GERAL
# ============================================================================

@router.get("", dependencies=[Depends(get_bff_token)])
def listar_catalogo(db: Session = Depends(get_db)):
    """Retorna o catálogo completo de serviços com todos os atributos."""
    try:
        return ServicoService.listar_geral(db)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar catálogo de serviços.")


@router.post("/catalogo", dependencies=[Depends(get_bff_token)])
def criar_servico(dados: ServicoCreate, db: Session = Depends(get_db)):
    """Cria um novo serviço no catálogo."""
    try:
        servico = ServicoService.criar_servico(db, dados.model_dump())
        return {"success": True, "ServicoID": servico.ServicoID, "Nome": servico.Nome}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao criar serviço.")


@router.put("/catalogo/{servico_id}", dependencies=[Depends(get_bff_token)])
def editar_servico(servico_id: int, dados: ServicoUpdate, db: Session = Depends(get_db)):
    """Edita um serviço existente. Suporta atualização parcial."""
    try:
        # Filtra apenas os campos que foram enviados (não None)
        payload = {k: v for k, v in dados.model_dump().items() if v is not None}
        servico = ServicoService.editar_servico(db, servico_id, payload)
        return {"success": True, "ServicoID": servico.ServicoID, "Nome": servico.Nome}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao editar serviço.")


# ============================================================================
# CONFIGURAÇÃO POR UNIDADE
# ============================================================================

@router.get("/unidades", dependencies=[Depends(get_bff_token)])
def listar_unidades_com_servicos(db: Session = Depends(get_db)):
    """
    Retorna todas as unidades com seus serviços configurados.
    Utilizado pela aba 'Controle por Unidade' da tela de Serviços.
    """
    try:
        return ServicoService.listar_servicos_completo_por_unidade(db)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao buscar configurações por unidade.")


@router.post("/vincular", dependencies=[Depends(get_bff_token)])
def vincular_servico_unidade(dados: VincularServicoUnidade, db: Session = Depends(get_db)):
    """
    Cria ou atualiza o vínculo de um serviço a uma unidade com preço configurado.
    Utiliza upsert (cria se não existir, atualiza se já existir).
    """
    try:
        config = ServicoService.vincular_servico_unidade(db, dados.model_dump())
        return {
            "success": True,
            "UnidadeID": config.UnidadeID,
            "ServicoID": config.ServicoID,
            "Preco": config.Preco,
            "Ativo": config.Ativo,
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao vincular serviço à unidade.")
