"""
Schemas Pydantic — Domínio: Backoffice & Métricas

Define os contratos de dados para:
  - KPIs de Conversão (taxa de aceite por atividade/cidade)
  - Balanço Demanda vs Oferta (índice de pressão por cidade/atividade)
  - Verificador de Cobertura (parceiros disponíveis por atividade em um ponto)
  - Dashboard Geral (envelope que agrega os dois KPIs + totalizadores)
"""

from typing import List, Optional
from pydantic import BaseModel


# ============================================================================
# KPI: CONVERSÃO
# ============================================================================

class KPIConversao(BaseModel):
    """Métricas de conversão de disparos por Atividade / Cidade / Bairro."""
    Atividade: Optional[str]
    Cidade: Optional[str]
    Bairro: Optional[str]
    Total_Disparos: Optional[int] = 0
    Total_Aceitos: Optional[int] = 0
    Total_Aceitos_Atrasado: Optional[int] = 0
    Total_Negados: Optional[int] = 0
    Total_Cancelados: Optional[int] = 0
    Total_Pendentes: Optional[int] = 0
    Taxa_Conversao_Pct: Optional[float] = 0.0
    Taxa_Interesse_Pct: Optional[float] = 0.0

    class Config:
        from_attributes = True


# ============================================================================
# KPI: BALANÇO DEMANDA vs OFERTA
# ============================================================================

class KPIBalanco(BaseModel):
    """Balanço entre pedidos abertos (demanda) e parceiros habilitados (oferta)."""
    Cidade: Optional[str]
    Atividade: Optional[str]
    Demanda_Mensal: Optional[int] = 0
    Oferta_Parceiros: Optional[int] = 0
    Indice_Pressao: Optional[float] = 0.0

    class Config:
        from_attributes = True


# ============================================================================
# VERIFICADOR DE COBERTURA
# ============================================================================

class CoberturaRequest(BaseModel):
    """Payload de entrada para verificação de cobertura geográfica."""
    endereco: str


class CoberturaItem(BaseModel):
    """Parceiros disponíveis para uma atividade em um ponto geográfico."""
    Atividade: str
    Parceiros_Disponiveis: int


class Coordenadas(BaseModel):
    """Coordenadas geocodificadas a partir do endereço fornecido."""
    lat: float
    lng: float


class CoberturaResponse(BaseModel):
    """Resposta completa do verificador de cobertura."""
    coordenadas: Optional[Coordenadas] = None
    cobertura: List[CoberturaItem] = []


# ============================================================================
# DASHBOARD GERAL (ENVELOPE)
# ============================================================================

class TotalizadoresDashboard(BaseModel):
    """Cards do topo da página: totais calculados no Backend."""
    total_disparos: int = 0
    total_aceitos: int = 0
    total_negados: int = 0
    taxa_media: float = 0.0


class DashboardResponse(BaseModel):
    """Resposta completa do endpoint GET /backoffice."""
    totalizadores: TotalizadoresDashboard
    kpi_conversao: List[KPIConversao] = []
    kpi_balanco: List[KPIBalanco] = []
