"""
Routes — Domínio: Estrutural (Hierarquia Administrativa)
Prefixo: /api/estrutural

Endpoints protegidos para o controle administrativo da hierarquia:
  Empresa → Filial → Unidade
"""

import traceback

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_bff_token
from app.services.unidades.unidade_service import UnidadeService
from app.schemas.estrutural import (
    EmpresaCreate, EmpresaUpdate,
    FilialCreate, FilialUpdate,
    UnidadeCreate, UnidadeUpdate,
)

router = APIRouter()


# ============================================================================
# GET — ESTRUTURA COMPLETA
# ============================================================================

@router.get("/admin", dependencies=[Depends(get_bff_token)])
def listar_estrutura_admin(db: Session = Depends(get_db)):
    """
    Retorna a árvore administrativa completa:
    Empresas, Filiais, Unidades e Cidades disponíveis.
    """
    try:
        return UnidadeService.listar_estrutural_completo(db)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao carregar estrutura administrativa.")


# ============================================================================
# EMPRESA
# ============================================================================

@router.post("/empresa", dependencies=[Depends(get_bff_token)])
def criar_empresa(dados: EmpresaCreate, db: Session = Depends(get_db)):
    """Cria uma nova Empresa."""
    try:
        empresa = UnidadeService.criar_empresa(db, dados.model_dump())
        return {"success": True, "EmpresaID": empresa.EmpresaID, "Nome": empresa.Nome}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao criar empresa.")


@router.put("/empresa/{empresa_id}", dependencies=[Depends(get_bff_token)])
def editar_empresa(empresa_id: int, dados: EmpresaUpdate, db: Session = Depends(get_db)):
    """Edita uma Empresa existente pelo ID."""
    try:
        empresa = UnidadeService.editar_empresa(db, empresa_id, dados.model_dump())
        return {"success": True, "EmpresaID": empresa.EmpresaID, "Nome": empresa.Nome}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao editar empresa.")


@router.delete("/empresa/{empresa_id}", dependencies=[Depends(get_bff_token)])
def deletar_empresa(empresa_id: int, db: Session = Depends(get_db)):
    """Remove uma Empresa pelo ID."""
    try:
        UnidadeService.deletar_empresa(db, empresa_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao deletar empresa.")


# ============================================================================
# FILIAL
# ============================================================================

@router.post("/filial", dependencies=[Depends(get_bff_token)])
def criar_filial(dados: FilialCreate, db: Session = Depends(get_db)):
    """Cria uma nova Filial vinculada a uma Empresa."""
    try:
        filial = UnidadeService.criar_filial(db, dados.model_dump())
        return {"success": True, "FilialID": filial.FilialID, "Nome": filial.Nome}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao criar filial.")


@router.put("/filial/{filial_id}", dependencies=[Depends(get_bff_token)])
def editar_filial(filial_id: int, dados: FilialUpdate, db: Session = Depends(get_db)):
    """Edita uma Filial existente pelo ID."""
    try:
        filial = UnidadeService.editar_filial(db, filial_id, dados.model_dump())
        return {"success": True, "FilialID": filial.FilialID, "Nome": filial.Nome}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao editar filial.")


@router.delete("/filial/{filial_id}", dependencies=[Depends(get_bff_token)])
def deletar_filial(filial_id: int, db: Session = Depends(get_db)):
    """Remove uma Filial pelo ID."""
    try:
        UnidadeService.deletar_filial(db, filial_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao deletar filial.")


# ============================================================================
# UNIDADE
# ============================================================================

@router.post("/unidade", dependencies=[Depends(get_bff_token)])
def criar_unidade(dados: UnidadeCreate, db: Session = Depends(get_db)):
    """Cria uma nova Unidade. Valida o CidadeID referenciado."""
    try:
        unidade = UnidadeService.criar_unidade(db, dados.model_dump())
        return {"success": True, "UnidadeID": unidade.UnidadeID, "NomeUnidade": unidade.NomeUnidade}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao criar unidade.")


@router.put("/unidade/{unidade_id}", dependencies=[Depends(get_bff_token)])
def editar_unidade(unidade_id: int, dados: UnidadeUpdate, db: Session = Depends(get_db)):
    """Edita uma Unidade existente pelo ID."""
    try:
        unidade = UnidadeService.editar_unidade(db, unidade_id, dados.model_dump())
        return {"success": True, "UnidadeID": unidade.UnidadeID, "NomeUnidade": unidade.NomeUnidade}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao editar unidade.")


@router.delete("/unidade/{unidade_id}", dependencies=[Depends(get_bff_token)])
def deletar_unidade(unidade_id: int, db: Session = Depends(get_db)):
    """Remove uma Unidade pelo ID."""
    try:
        UnidadeService.deletar_unidade(db, unidade_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erro ao deletar unidade.")
