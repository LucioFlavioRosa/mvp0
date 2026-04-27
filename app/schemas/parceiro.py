from pydantic import BaseModel, Field
from typing import Optional, List
import uuid

# ============================================================================
# SCHEMAS DE RESPOSTA: GET /parceiros  (Listar Parceiros)
# ============================================================================

class ParceiroResumoResponse(BaseModel):
    """Dados de um parceiro na listagem geral."""
    ParceiroUUID: str
    NomeCompleto: Optional[str]
    Cidade: Optional[str]
    Bairro: Optional[str]
    FotoUrl: Optional[str]
    TelefoneFormatado: Optional[str]
    TipoDocumento: Optional[str]
    DocumentoFormatado: Optional[str]
    HabilidadesList: List[str]
    RaioAtuacao: Optional[float]
    StatusAtual: Optional[str]
    StatusLabel: Optional[str]
    Veiculos: Optional[str]
    HabIDs: Optional[str]
    TotalOrdensConcluidas: Optional[int]

    class Config:
        from_attributes = True


class ListarParceirosResponse(BaseModel):
    """Resposta completa do endpoint de listagem de parceiros."""
    parceiros: List[ParceiroResumoResponse]
    total_ativos: int
    total_analise: int
    total_outros: int
    cidades: List[str]


# ============================================================================
# SCHEMAS DE RESPOSTA: GET /parceiros/{parceiro_uuid}  (Detalhe do Parceiro)
# ============================================================================

class OrdemVinculadaResponse(BaseModel):
    """Dados de uma ordem de serviço vinculada ao parceiro."""
    OrdemID: str
    PedidoID: str
    Atividade: Optional[str]
    CidadePedido: Optional[str]
    Urgencia: Optional[str]
    StatusOrdem: Optional[str]


class ParceiroPerfilResponse(BaseModel):
    """Perfil principal do parceiro no endpoint de detalhe."""
    ParceiroUUID: str
    NomeCompleto: Optional[str]
    Cidade: Optional[str]
    TelefoneFormatado: Optional[str]
    Email: Optional[str]
    TipoDocumento: Optional[str]
    DocumentoFormatado: Optional[str]
    StatusAtual: Optional[str]
    StatusLabel: Optional[str]
    EnderecoCompleto: Optional[str]
    DistanciaMaximaKm: Optional[float]
    ChavePix: Optional[str]
    Aceite: bool
    FotoUrl: Optional[str]


class DetalheParceiroResponse(BaseModel):
    """Resposta completa do endpoint de detalhe do parceiro."""
    parceiro: ParceiroPerfilResponse
    habilidades: List[str]
    disponibilidade: List[str]
    ordens: List[OrdemVinculadaResponse]


# ============================================================================
# SCHEMAS DE RESPOSTA: GET /parceiros/vinculados/os  (Parceiros com OS)
# ============================================================================

class OrdemOSResponse(BaseModel):
    """Dados de uma ordem de serviço no contexto de parceiros+OS."""
    PedidoID: str
    AtividadeDesc: Optional[str]
    CidadePedido: Optional[str]
    Urgencia: Optional[str]
    DataLimiteFormatada: Optional[str]
    StatusOrdem: Optional[str]


class ParceiroComOSResponse(BaseModel):
    """Dados de um parceiro e suas ordens vinculadas na tela Parceiros+OS."""
    ParceiroUUID: str
    NomeCompleto: Optional[str]
    Cidade: Optional[str]
    TelefoneFormatado: Optional[str]
    TipoDocumento: Optional[str]
    DocumentoFormatado: Optional[str]
    StatusAtual: Optional[str]
    StatusLabel: Optional[str]
    FotoUrl: Optional[str]
    ordens: List[OrdemOSResponse]


class ParceirosComOSResponse(BaseModel):
    """Resposta completa do endpoint de parceiros com ordens vinculadas."""
    parceiros_os: List[ParceiroComOSResponse]
