from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

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
    Lat: Optional[str]
    Lng: Optional[str]
    PrazoConclusaoOS: Optional[str] # Formatado como string
    Atividade: str # Nome do serviço (Vindo do relacionamento)
    TempoMedio: Optional[float] # Tempo médio (Vindo do relacionamento)
    UnidadeNome: Optional[str] # Nome da unidade (Vindo do relacionamento)

    class Config:
        from_attributes = True

class PedidosListResponse(BaseModel):
    pedidos: List[PedidoResponse]
    total: int
    filtros_disponiveis: dict
