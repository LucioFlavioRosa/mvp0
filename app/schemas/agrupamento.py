"""
Schemas Pydantic — Domínio: Agrupamentos de OS (Lote)

Define os contratos de dados para:
  - Detalhes de um agrupamento: pedidos elegíveis e parceiros compatíveis com o lote
  - Disparo em lote: lista de pedidos + parceiros selecionados
  - Resposta do disparo em lote
"""

from typing import List, Optional
from pydantic import BaseModel


# ============================================================================
# DETALHES DO AGRUPAMENTO (GET)
# ============================================================================

class PedidoAgrupamentoItem(BaseModel):
    """Dados de um pedido formatado para exibição no agrupamento."""
    PedidoID: str
    Atividade: str
    Rua: Optional[str]
    Numero: Optional[str]
    Bairro: Optional[str]
    Cidade: Optional[str]
    PrazoConclusaoOS: Optional[str]   # Formatado: dd/mm/yyyy HH:MM
    TempoMedio: Optional[str]
    Urgencia: Optional[str]
    StatusPedido: str
    Lat: float
    Lng: float

    class Config:
        from_attributes = True


class ParceiroAgrupamentoItem(BaseModel):
    """Dados de um parceiro compatível com o lote, incluindo detalhes para o modal."""
    ParceiroUUID: str
    NomeCompleto: Optional[str]
    Cidade: Optional[str]
    Bairro: Optional[str]
    TelefoneFormatado: Optional[str]
    FotoUrl: Optional[str]
    StatusAtual: Optional[str]
    StatusLabel: Optional[str]
    Lat: Optional[float]
    Lon: Optional[float]
    distancia: Optional[float]  # km até o centroide do agrupamento

    # Campos extras para o Modal de Perfil no Portal
    Veiculos: Optional[str]
    HabilidadesList: List[str] = []
    Email: Optional[str]
    TipoDocumento: Optional[str]
    DocumentoFormatado: Optional[str]
    EnderecoCompleto: Optional[str]
    DistanciaMaximaKm: Optional[float]
    TotalOrdensConcluidas: int = 0
    DisponibilidadeList: List[str] = []

    class Config:
        from_attributes = True


class CentroideAgrupamento(BaseModel):
    """Centroide geográfico calculado a partir das coordenadas dos pedidos."""
    lat: float
    lng: float


class AgrupamentoDetalhesResponse(BaseModel):
    """Resposta completa do endpoint GET /agrupamentos/detalhes."""
    pedidos: List[PedidoAgrupamentoItem] = []
    parceiros: List[ParceiroAgrupamentoItem] = []
    centroide: Optional[CentroideAgrupamento] = None
    total_pedidos: int = 0
    total_parceiros: int = 0


# ============================================================================
# DISPARO EM LOTE (POST)
# ============================================================================

class DisparoLoteRequest(BaseModel):
    """Payload de entrada para o disparo em lote."""
    id_pedidos: List[str]
    parceiros_selecionados: List[str]


class DisparoLoteResponse(BaseModel):
    """Resposta do disparo em lote."""
    success: bool
    message: str
    sucessos: int = 0
    falhas: int = 0
