"""
Schemas Pydantic — Domínio: Catálogo de Serviços & Materiais

Define os contratos de dados para:
  - Catálogo administrativo de Serviços
  - Configuração de preços por Unidade
"""

from typing import Optional
from pydantic import BaseModel


# ============================================================================
# CATÁLOGO DE SERVIÇOS
# ============================================================================

class ServicoCreate(BaseModel):
    codigo_servico: str
    nome: str
    descricao: str
    tipo_veiculo: Optional[str] = None
    epi: Optional[str] = None
    perfil: Optional[str] = None
    formulario_resposta: Optional[str] = None
    tempo_medio_execucao: Optional[float] = None
    tempo_maximo: Optional[float] = None


class ServicoUpdate(BaseModel):
    """Todos os campos são opcionais para suportar atualização parcial."""
    codigo_servico: Optional[str] = None
    nome: Optional[str] = None
    descricao: Optional[str] = None
    tipo_veiculo: Optional[str] = None
    epi: Optional[str] = None
    perfil: Optional[str] = None
    formulario_resposta: Optional[str] = None
    tempo_medio_execucao: Optional[float] = None
    tempo_maximo: Optional[float] = None


# ============================================================================
# CONFIGURAÇÃO DE PREÇO POR UNIDADE
# ============================================================================

class VincularServicoUnidade(BaseModel):
    """Payload para criar ou atualizar a configuração de um serviço em uma unidade."""
    unidade_id: int
    servico_id: int
    preco: float = 0.0
    fator_extra: float = 1.0
    ativo: bool = True
