from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid
import re

# ============================================================================
# UTILS (Formatação para Response)
# ============================================================================
def formatar_telefone(telefone: Optional[str]) -> str:
    if not telefone: return "Não informado"
    nums = re.sub(r'\D', '', str(telefone))
    if len(nums) == 11: return f"({nums[:2]}) {nums[2:7]}-{nums[7:]}"
    if len(nums) == 10: return f"({nums[:2]}) {nums[2:6]}-{nums[6:]}"
    return telefone

def formatar_documento(doc: Optional[str]) -> str:
    if not doc: return "Não informado"
    nums = re.sub(r'\D', '', str(doc))
    if len(nums) == 11: return f"{nums[:3]}.{nums[3:6]}.{nums[6:9]}-{nums[9:]}"
    if len(nums) == 14: return f"{nums[:2]}.{nums[2:5]}.{nums[5:8]}/{nums[8:12]}-{nums[12:]}"
    return doc

def gerar_url_foto(uuid_val) -> str:
    if not uuid_val: return ""
    uuid_str = str(uuid_val).upper().strip()
    return f"https://staegeadocscaddevusc.blob.core.windows.net/selfie/{uuid_str}/selfie.jpg"

# ============================================================================
# SCHEMAS
# ============================================================================
class PedidoResponse(BaseModel):
    PedidoID: uuid.UUID
    TipoServicoID: int
    UnidadeID: Optional[int]
    StatusPedido: Optional[str]
    Urgencia: Optional[str]
    Bloco: Optional[str]
    CEP: Optional[str]
    Cidade: Optional[str]
    Bairro: Optional[str]
    Rua: Optional[str]
    Numero: Optional[str]
    Complemento: Optional[str]
    Valor: Optional[float]
    Lat: Optional[float]
    Lng: Optional[float]
    PrazoConclusaoOS: Optional[datetime] 
    Atividade: str 
    TempoMedio: Optional[float] 
    UnidadeNome: Optional[str] 

    class Config:
        from_attributes = True

class PedidosListResponse(BaseModel):
    pedidos: List[PedidoResponse]
    filtros_disponiveis: dict

class DesvincularRequest(BaseModel):
    mensagem: Optional[str] = Field(None, description="Mensagem opcional de justificativa")

class PedidoCreateRequest(BaseModel):
    TipoServicoID: int
    UnidadeID: int
    Bloco: str
    Rua: str
    Numero: str
    Bairro: str
    Cidade: str
    CEP: str
    MatriculaSCAE: str
    NumeroOSSCAE: str
    DataAberturaSCAE: datetime
    PrazoConclusaoOS: datetime
    Urgencia: str
    Observacao: Optional[str] = None
    Complemento: Optional[str] = None
    Valor: float
    Lat: Optional[float] = None
    Lng: Optional[float] = None
    ParceiroAlocadoUUID: Optional[uuid.UUID] = None
    StatusPedido: Optional[str] = "AGUARDANDO"

class PedidoUpdateRequest(BaseModel):
    TipoServicoID: Optional[int] = None
    UnidadeID: Optional[int] = None
    Bloco: Optional[str] = None
    Rua: Optional[str] = None
    Numero: Optional[str] = None
    Bairro: Optional[str] = None
    Cidade: Optional[str] = None
    CEP: Optional[str] = None
    MatriculaSCAE: Optional[str] = None
    NumeroOSSCAE: Optional[str] = None
    DataAberturaSCAE: Optional[datetime] = None
    PrazoConclusaoOS: Optional[datetime] = None
    Urgencia: Optional[str] = None
    Observacao: Optional[str] = None
    Complemento: Optional[str] = None
    Valor: Optional[float] = None
    Lat: Optional[float] = None
    Lng: Optional[float] = None
    ParceiroAlocadoUUID: Optional[uuid.UUID] = None
    StatusPedido: Optional[str] = None

class ParceiroDetalheResponse(BaseModel):
    ParceiroUUID: uuid.UUID
    NomeCompleto: Optional[str]
    Rua: Optional[str]
    Bairro: Optional[str]
    Cidade: Optional[str]
    CEP: Optional[str]
    Telefone: Optional[str]
    Documento: Optional[str]
    CPF: Optional[str]
    CNPJ: Optional[str]
    StatusAtual: Optional[str]
    Lat: Optional[float]
    Lon: Optional[float]
    Veiculos: Optional[str]
    TotalOrdensConcluidas: Optional[int]
    distancia: Optional[float]
    FotoUrl: Optional[str]
    
    @classmethod
    def from_orm_model(cls, obj, lat_pedido: float = None, lng_pedido: float = None) -> 'ParceiroDetalheResponse':
        # Distancia e formatações
        dist = 999.0
        if lat_pedido and lng_pedido and obj.Lat and getattr(obj, 'Lon', None):
            try:
                from geopy.distance import geodesic
                dist = round(geodesic((obj.Lat, obj.Lon), (lat_pedido, lng_pedido)).kilometers, 2)
            except Exception: pass
            
        doc = obj.CPF if obj.CPF else getattr(obj, 'CNPJ', None)
        
        return cls(
            ParceiroUUID=obj.ParceiroUUID,
            NomeCompleto=obj.NomeCompleto,
            Rua=obj.Rua,
            Bairro=obj.Bairro,
            Cidade=obj.Cidade,
            CEP=obj.CEP,
            Telefone=formatar_telefone(obj.Telefone),
            Documento=formatar_documento(doc),
            CPF=obj.CPF,
            CNPJ=getattr(obj, 'CNPJ', None),
            StatusAtual=obj.StatusAtual,
            Lat=obj.Lat,
            Lon=getattr(obj, 'Lon', None),
            Veiculos=getattr(obj, 'Veiculos', ''),
            TotalOrdensConcluidas=getattr(obj, 'TotalOrdensConcluidas', 0),
            distancia=dist,
            FotoUrl=gerar_url_foto(obj.ParceiroUUID)
        )

class PedidoDetalheCompletoResponse(BaseModel):
    pedido: PedidoResponse
    parceiros: List[dict] # BFF was expecting a dict actually, we will serialize it in Route.
