"""
Schemas Pydantic — Domínio: Estrutural (Hierarquia Administrativa)

Define os contratos de dados para:
  - Listagem completa da árvore (Empresa → Filial → Unidade)
  - CRUD de Empresas, Filiais e Unidades
"""

from typing import List, Optional
from pydantic import BaseModel


# ============================================================================
# EMPRESA
# ============================================================================

class EmpresaBase(BaseModel):
    nome: str
    cnpj: Optional[str] = None

class EmpresaCreate(EmpresaBase):
    pass

class EmpresaUpdate(EmpresaBase):
    pass

class EmpresaResponse(BaseModel):
    EmpresaID: int
    Nome: str
    CNPJ: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================================================
# FILIAL
# ============================================================================

class FilialBase(BaseModel):
    empresa_id: int
    nome: str
    cnpj: Optional[str] = None
    regiao: Optional[str] = None
    estado: Optional[str] = None

class FilialCreate(FilialBase):
    pass

class FilialUpdate(FilialBase):
    pass

class FilialResponse(BaseModel):
    FilialID: int
    EmpresaID: int
    Nome: str
    CNPJ: Optional[str] = None
    Regiao: Optional[str] = None
    Estado: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================================================
# UNIDADE
# ============================================================================

class UnidadeBase(BaseModel):
    filial_id: Optional[int] = None
    cidade_id: int
    nome_unidade: str
    cnpj: Optional[str] = None
    codigo_filial: Optional[str] = None
    bloco: Optional[str] = None
    materiais: Optional[str] = None

class UnidadeCreate(UnidadeBase):
    pass

class UnidadeUpdate(UnidadeBase):
    pass

class UnidadeResponse(BaseModel):
    UnidadeID: int
    FilialID: Optional[int] = None
    CidadeID: int
    NomeUnidade: str
    CNPJ: Optional[str] = None
    CodigoFilial: Optional[str] = None
    Bloco: Optional[str] = None
    FornecimentoMateriais: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================================================
# CIDADE (apenas para listagem)
# ============================================================================

class CidadeResponse(BaseModel):
    CidadeID: int
    NomeCidade: str
    SubregiaoID: int

    class Config:
        from_attributes = True


# ============================================================================
# RESPOSTA CONSOLIDADA (GET /api/estrutural/admin)
# ============================================================================

class EstruturaAdminResponse(BaseModel):
    """Resposta completa do endpoint GET /api/estrutural/admin."""
    empresas: List[EmpresaResponse] = []
    filiais: List[FilialResponse] = []
    unidades: List[UnidadeResponse] = []
    cidades: List[CidadeResponse] = []
