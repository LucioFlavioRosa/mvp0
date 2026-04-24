from typing import Optional, List
import datetime
import uuid

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, 
    Identity, Integer, String, Table, Unicode, Uuid, text
)
from sqlalchemy.dialects.mssql import DATETIME2
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

# Importamos a Base centralizada de app.core.database
from app.core.database import Base

# ============================================================================
# TIPOS CUSTOMIZADOS
# ============================================================================

class Geography(UserDefinedType):
    """Suporte para o tipo espacial 'geography' do SQL Server"""
    cache_ok = True
    def get_col_spec(self, **kw):
        return "geography"

# ============================================================================
# MODELOS
# ============================================================================

# ============================================================================
# HIERARQUIA ORGANIZACIONAL, MATERIAIS E AUDITORIA
# ============================================================================

class Empresa(Base):
    __tablename__ = 'EMPRESAS'

    EmpresaID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    Nome: Mapped[str] = mapped_column(String(200), nullable=False)
    CNPJ: Mapped[Optional[str]] = mapped_column(String(20))

    filiais: Mapped[List['Filial']] = relationship(back_populates='empresa')


class Filial(Base):
    __tablename__ = 'FILIAIS'    

    FilialID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    EmpresaID: Mapped[int] = mapped_column(ForeignKey('EMPRESAS.EmpresaID'), nullable=False)
    Nome: Mapped[str] = mapped_column(String(200), nullable=False)
    CNPJ: Mapped[Optional[str]] = mapped_column(String(20))
    Regiao: Mapped[Optional[str]] = mapped_column(String(100))
    Estado: Mapped[Optional[str]] = mapped_column(String(2))

    empresa: Mapped['Empresa'] = relationship(back_populates='filiais')
    unidades: Mapped[List['Unidade']] = relationship(back_populates='filial')


class Material(Base):
    __tablename__ = 'MATERIAIS'

    MaterialID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    Descricao: Mapped[str] = mapped_column(String(200), nullable=False)
    TipoMaterial: Mapped[Optional[str]] = mapped_column(String(100))


class LogAuditoria(Base):
    __tablename__ = 'LOGS_AUDITORIA'

    LogID: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    Acao: Mapped[str] = mapped_column(String(100), nullable=False)
    TabelaAfetada: Mapped[Optional[str]] = mapped_column(String(100))
    RegistroID: Mapped[Optional[str]] = mapped_column(String(100))
    UsuarioID: Mapped[Optional[str]] = mapped_column(String(100))
    DetalhesAntigos: Mapped[Optional[str]] = mapped_column(Unicode)
    DetalhesNovos: Mapped[Optional[str]] = mapped_column(Unicode)
    DataHora: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=text('(getdate())'))

class CatalogoRegiao(Base):
    __tablename__ = 'CATALOGO_REGIOES'
    
    RegiaoID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    NomeRegiao: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Relacionamentos
    subregioes: Mapped[List['CatalogoSubregiao']] = relationship(back_populates='regiao')


class CatalogoSubregiao(Base):
    __tablename__ = 'CATALOGO_SUBREGIOES'

    SubregiaoID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    RegiaoID: Mapped[int] = mapped_column(ForeignKey('CATALOGO_REGIOES.RegiaoID'), nullable=False)
    NomeSubregiao: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relacionamentos
    regiao: Mapped['CatalogoRegiao'] = relationship(back_populates='subregioes')
    cidades: Mapped[List['CatalogoCidadePara']] = relationship(back_populates='subregiao')


class CatalogoCidadePara(Base):
    __tablename__ = 'CATALOGO_CIDADES_PARA'

    CidadeID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    SubregiaoID: Mapped[int] = mapped_column(ForeignKey('CATALOGO_SUBREGIOES.SubregiaoID'), nullable=False)
    NomeCidade: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relacionamentos
    subregiao: Mapped['CatalogoSubregiao'] = relationship(back_populates='cidades')
    unidades: Mapped[List['Unidade']] = relationship(back_populates='cidade_obj')


class Unidade(Base):
    __tablename__ = 'UNIDADES'

    UnidadeID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    CidadeID: Mapped[int] = mapped_column(ForeignKey('CATALOGO_CIDADES_PARA.CidadeID'), nullable=False)
    NomeUnidade: Mapped[str] = mapped_column(String(100), nullable=False)
    CNPJ: Mapped[Optional[str]] = mapped_column(String(20))

    FilialID: Mapped[Optional[int]] = mapped_column(ForeignKey('FILIAIS.FilialID'))
    CodigoFilial: Mapped[Optional[str]] = mapped_column(String(50))
    Bloco: Mapped[Optional[str]] = mapped_column(String(50))
    FornecimentoMateriais: Mapped[Optional[str]] = mapped_column(Unicode)

    # Relacionamentos
    cidade_obj: Mapped['CatalogoCidadePara'] = relationship(back_populates='unidades')
    filial: Mapped[Optional['Filial']] = relationship(back_populates='unidades')
    parceiros_alocados: Mapped[List['ParceiroPerfil']] = relationship(back_populates='unidade_vinculada')
    servicos_configurados: Mapped[List['PrecoServicoUnidade']] = relationship(back_populates='unidade_ref')

class CatalogoServico(Base):
    __tablename__ = 'CATALOGO_SERVICOS'

    ServicoID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    CodigoServico: Mapped[str] = mapped_column(String(50), nullable=False) # Vem do SCAE
    Nome: Mapped[str] = mapped_column(String(100), nullable=False)
    Descricao: Mapped[str] = mapped_column(String(200), nullable=False)
    TipoVeiculo: Mapped[Optional[int]] = mapped_column(ForeignKey('TIPOS_VEICULOS.TipoVeiculoID'), nullable=True)
    EPI: Mapped[Optional[str]] = mapped_column(String(10))
    Perfil: Mapped[Optional[str]] = mapped_column(String(50))
    FormularioResposta: Mapped[Optional[str]] = mapped_column(String(500))
    TempoMedioExecucao: Mapped[Optional[float]] = mapped_column(Float)
    TempoMaximo: Mapped[Optional[float]] = mapped_column(Float)

    # Relacionamentos
    precos_unidade: Mapped[List['PrecoServicoUnidade']] = relationship(back_populates='servico_ref')

class PrecoServicoUnidade(Base):
    __tablename__ = 'PRECOS_SERVICOS_UNIDADE'

    UnidadeID: Mapped[int] = mapped_column(ForeignKey('UNIDADES.UnidadeID'), primary_key=True)
    ServicoID: Mapped[int] = mapped_column(ForeignKey('CATALOGO_SERVICOS.ServicoID'), primary_key=True)
    
    Preco: Mapped[float] = mapped_column(Float(53), nullable=False, default=0.0)
    FatorExtra: Mapped[Optional[float]] = mapped_column(Float, default=1.0)
    Ativo: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('((1))'))

    # Relacionamentos
    unidade_ref: Mapped['Unidade'] = relationship(back_populates='servicos_configurados')
    servico_ref: Mapped['CatalogoServico'] = relationship(back_populates='precos_unidade')

class ServicoUnidadeMaterial(Base):
    __tablename__ = 'SERVICOS_UNIDADES_MATERIAIS'

    UnidadeID: Mapped[int] = mapped_column(ForeignKey('UNIDADES.UnidadeID'), primary_key=True)
    ServicoID: Mapped[int] = mapped_column(ForeignKey('CATALOGO_SERVICOS.ServicoID'), primary_key=True)
    MaterialID: Mapped[int] = mapped_column(ForeignKey('MATERIAIS.MaterialID'), primary_key=True)
    Obrigatorio: Mapped[bool] = mapped_column(Boolean, server_default=text('((0))'))

# ============================================================================
# MODELOS DE PARCEIROS
# ============================================================================

class ParceiroPerfil(Base):
    __tablename__ = 'PARCEIROS_PERFIL'

    ParceiroUUID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('(newid())'))
    UnidadeID: Mapped[int] = mapped_column(ForeignKey('UNIDADES.UnidadeID'), nullable=False)
    WhatsAppID: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    CNPJ: Mapped[Optional[str]] = mapped_column(String(20))
    CPF: Mapped[Optional[str]] = mapped_column(String(20))
    NomeCompleto: Mapped[Optional[str]] = mapped_column(String(255))
    StatusAtual: Mapped[Optional[str]] = mapped_column(String(20), server_default=text("('EM_ANALISE')"))
    CEP: Mapped[Optional[str]] = mapped_column(String(15))
    Rua: Mapped[Optional[str]] = mapped_column(String(255))
    Numero: Mapped[Optional[int]] = mapped_column(Integer)
    Bairro: Mapped[Optional[str]] = mapped_column(String(100))
    Cidade: Mapped[Optional[str]] = mapped_column(String(100))
    Geo_Base: Mapped[Optional[str]] = mapped_column(Geography)
    chave_pix: Mapped[Optional[str]] = mapped_column(String(100))
    Aceite: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('((0))'))
    DistanciaMaximaKm: Mapped[Optional[float]] = mapped_column(Float(53))
    Email: Mapped[Optional[str]] = mapped_column(String(255))

    Qualificacao_DDI: Mapped[str] = mapped_column(String(50), nullable=False)
    TreinamentoFlag: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('((0))'))
    Perfil: Mapped[str] = mapped_column(String(50), nullable=False)

    # Relacionamentos
    unidade_vinculada: Mapped[Optional['Unidade']] = relationship(back_populates='parceiros_alocados')
    disponibilidades: Mapped[List['ParceiroDisponibilidade']] = relationship(back_populates='parceiro')
    docs: Mapped[List['ParceiroDocLegal']] = relationship(back_populates='parceiro')
    habilidades: Mapped[List['ParceiroHabilidade']] = relationship(back_populates='parceiro')
    veiculos: Mapped[List['ParceiroVeiculo']] = relationship(back_populates='parceiro')
    disparos: Mapped[List['PedidoDisparo']] = relationship(back_populates='parceiro')
    ordens_alocadas: Mapped[List['OrdemServico']] = relationship(back_populates='parceiro_alocado')
    pedidos_alocados: Mapped[List['PedidoServico']] = relationship(back_populates='parceiro_alocado')
    interacoes: Mapped[List['InteracaoChat']] = relationship(back_populates='parceiro')


class ParceiroDisponibilidade(Base):
    __tablename__ = 'PARCEIROS_DISPONIBILIDADE'

    DisponibilidadeID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('(newid())'))
    ParceiroUUID: Mapped[uuid.UUID] = mapped_column(ForeignKey('PARCEIROS_PERFIL.ParceiroUUID'), nullable=False)
    DiaSemana: Mapped[Optional[int]] = mapped_column(Integer)
    Periodo: Mapped[Optional[int]] = mapped_column(Integer)
    Ativo: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('((1))'))

    # Relacionamentos
    parceiro: Mapped['ParceiroPerfil'] = relationship(back_populates='disponibilidades')


class ParceiroDocLegal(Base):
    __tablename__ = 'PARCEIROS_DOCS_LEGAIS'

    DocID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    ParceiroUUID: Mapped[uuid.UUID] = mapped_column(ForeignKey('PARCEIROS_PERFIL.ParceiroUUID'), nullable=False)
    TipoDocumento: Mapped[Optional[str]] = mapped_column(String(20))
    BlobPath: Mapped[Optional[str]] = mapped_column(String(500))
    StatusValidacao: Mapped[Optional[str]] = mapped_column(String(20), server_default=text("('PENDENTE')"))

    # Relacionamentos
    parceiro: Mapped['ParceiroPerfil'] = relationship(back_populates='docs')


class ParceiroHabilidade(Base):
    __tablename__ = 'PARCEIROS_HABILIDADES'

    HabilidadeID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('(newid())'))
    ParceiroUUID: Mapped[uuid.UUID] = mapped_column(ForeignKey('PARCEIROS_PERFIL.ParceiroUUID'), nullable=False)
    TipoServicoID: Mapped[int] = mapped_column(ForeignKey('CATALOGO_SERVICOS.ServicoID'), nullable=False)
    TempoExperiencia: Mapped[Optional[int]] = mapped_column(Integer)

    # Relacionamentos
    parceiro: Mapped['ParceiroPerfil'] = relationship(back_populates='habilidades')


class TipoVeiculo(Base):
    __tablename__ = 'TIPOS_VEICULOS'

    TipoVeiculoID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    NomeVeiculo: Mapped[str] = mapped_column(String(50), nullable=False)

    # Relacionamentos
    veiculos: Mapped[List['ParceiroVeiculo']] = relationship(back_populates='tipo_veiculo')


class ParceiroVeiculo(Base):
    __tablename__ = 'PARCEIROS_VEICULOS'

    VeiculoID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('(newid())'))
    ParceiroUUID: Mapped[uuid.UUID] = mapped_column(ForeignKey('PARCEIROS_PERFIL.ParceiroUUID'), nullable=False)
    TipoVeiculoID: Mapped[int] = mapped_column(Integer, ForeignKey('TIPOS_VEICULOS.TipoVeiculoID'), nullable=False)
    Placa: Mapped[Optional[str]] = mapped_column(String(10))
    Ativo: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('((1))'))

    # Relacionamentos
    parceiro: Mapped['ParceiroPerfil'] = relationship(back_populates='veiculos')
    tipo_veiculo: Mapped['TipoVeiculo'] = relationship(back_populates='veiculos')

# ============================================================================
# MODELOS DE PEDIDOS E OPERAÇÃO
# ============================================================================

class PedidoServico(Base):
    __tablename__ = 'PEDIDOS_SERVICO'

    PedidoID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('(newid())'))
    MatriculaSCAE: Mapped[str] = mapped_column(String(50), nullable=False)
    NumeroOSSCAE: Mapped[str] = mapped_column(String(100), nullable=False)
    CEP: Mapped[str] = mapped_column(String(10), nullable=False)
    Cidade: Mapped[str] = mapped_column(String(100), nullable=False)
    Bairro: Mapped[str] = mapped_column(String(100), nullable=False)
    Rua: Mapped[str] = mapped_column(String(200), nullable=False)
    Numero: Mapped[str] = mapped_column(String(20), nullable=False)
    TipoServicoID: Mapped[int] = mapped_column(ForeignKey('CATALOGO_SERVICOS.ServicoID'), nullable=False)
    Bloco: Mapped[str] = mapped_column(String(50), nullable=False)
    Observacao: Mapped[Optional[str]] = mapped_column(Unicode)
    Urgencia: Mapped[str] = mapped_column(String(50), nullable=False)
    PrazoConclusaoOS: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    DataAberturaSCAE: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    DataCriacao: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('(getdate())'))
    StatusPedido: Mapped[str] = mapped_column(String(20), server_default=text("('AGUARDANDO')"), nullable=False)
    Valor: Mapped[float] = mapped_column(Float(53), nullable=False)
    Complemento: Mapped[Optional[str]] = mapped_column(String(200))
    UnidadeID: Mapped[int] = mapped_column(ForeignKey('UNIDADES.UnidadeID'), nullable=False)
    ParceiroAlocadoUUID: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey('PARCEIROS_PERFIL.ParceiroUUID'))
    CriadoPor: Mapped[str] = mapped_column(String(255), server_default=text("('SYSTEM')"))
    Lat: Mapped[Optional[float]] = mapped_column(Float(53))
    Lng: Mapped[Optional[float]] = mapped_column(Float(53))

    # Relacionamentos
    tipo_servico_ref: Mapped['CatalogoServico'] = relationship()
    parceiro_alocado: Mapped[Optional['ParceiroPerfil']] = relationship(back_populates='pedidos_alocados')
    unidade_obj: Mapped[Optional['Unidade']] = relationship()
    disparos: Mapped[List['PedidoDisparo']] = relationship(back_populates='pedido')
    ordem: Mapped[Optional['OrdemServico']] = relationship(back_populates='pedido_obj')
    interacoes: Mapped[List['InteracaoChat']] = relationship(back_populates='pedido')
    passos: Mapped[List['ExecucaoPassoRastreavel']] = relationship(back_populates='pedido')
    agrupamentos_vinculados: Mapped[List['AgrupamentoOS']] = relationship(back_populates='pedido')

class PedidoDisparo(Base):
    __tablename__ = 'PEDIDOS_DISPAROS'

    DisparoID: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    PedidoID: Mapped[uuid.UUID] = mapped_column(ForeignKey('PEDIDOS_SERVICO.PedidoID'), nullable=False)
    ParceiroUUID: Mapped[uuid.UUID] = mapped_column(ForeignKey('PARCEIROS_PERFIL.ParceiroUUID'), nullable=False)
    Status: Mapped[str] = mapped_column(String(20), nullable=False)
    DataAtualizacao: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('(getdate())'))

    # Relacionamentos
    pedido: Mapped['PedidoServico'] = relationship(back_populates='disparos')
    parceiro: Mapped['ParceiroPerfil'] = relationship(back_populates='disparos')


# Essa tabela será removida posteriormente (Iremos usar apenas PEDIDOS_SERVICO)
class OrdemServico(Base):
    __tablename__ = 'ORDENS_SERVICO'

    OrdemID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('(newid())'))
    ParceiroAlocadoUUID: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey('PARCEIROS_PERFIL.ParceiroUUID'))
    TipoServicoID: Mapped[int] = mapped_column(ForeignKey('CATALOGO_SERVICOS.ServicoID'), nullable=False)
    StatusOrdem: Mapped[Optional[str]] = mapped_column(String(20), server_default=text("('ABERTA')"))
    PedidoID: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey('PEDIDOS_SERVICO.PedidoID'))
    UnidadeID: Mapped[Optional[int]] = mapped_column(ForeignKey('UNIDADES.UnidadeID'))

    # Relacionamentos
    unidade_obj: Mapped[Optional['Unidade']] = relationship()
    parceiro_alocado: Mapped[Optional['ParceiroPerfil']] = relationship(back_populates='ordens_alocadas')
    pedido_obj: Mapped[Optional['PedidoServico']] = relationship(back_populates='ordem')
    # passos: Mapped[List['ExecucaoPassoRastreavel']] = relationship(back_populates='ordem')
    # interacoes: Mapped[List['InteracaoChat']] = relationship(back_populates='ordem')


class ExecucaoPassoRastreavel(Base):
    __tablename__ = 'EXECUCAO_PASSOS_RASTREAVEIS'

    PassoID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('(newid())'))
    # OrdemID: Mapped[uuid.UUID] = mapped_column(ForeignKey('ORDENS_SERVICO.OrdemID'), nullable=False)
    PedidoID: Mapped[uuid.UUID] = mapped_column(ForeignKey('PEDIDOS_SERVICO.PedidoID'), nullable=False)
    Etapa: Mapped[Optional[str]] = mapped_column(String(100))
    BlobPath_Evidencia: Mapped[Optional[str]] = mapped_column(String(500))
    Geo_GPS_Real: Mapped[Optional[str]] = mapped_column(Geography)
    Timestamp_Envio: Mapped[Optional[datetime.datetime]] = mapped_column(DATETIME2, server_default=text('(getdate())'))

    # Relacionamentos
    # ordem: Mapped['OrdemServico'] = relationship(back_populates='passos')
    pedido: Mapped['PedidoServico'] = relationship(back_populates='passos')

# ============================================================================
# MODELOS DE COMUNICAÇÃO (WPP)
# ============================================================================

class ChatSession(Base):
    __tablename__ = 'CHAT_SESSIONS'

    WhatsAppID: Mapped[str] = mapped_column(String(50), primary_key=True)
    CurrentStep: Mapped[Optional[str]] = mapped_column(String(100))
    StepBackup: Mapped[Optional[str]] = mapped_column(String(100))
    TempData: Mapped[Optional[str]] = mapped_column(Unicode)
    LastUpdate: Mapped[Optional[datetime.datetime]] = mapped_column(DATETIME2, server_default=text('(getdate())'))


class InteracaoChat(Base):
    __tablename__ = 'INTERACOES_CHAT'

    ChatID: Mapped[int] = mapped_column(BigInteger, Identity(start=1, increment=1), primary_key=True)
    ParceiroUUID: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey('PARCEIROS_PERFIL.ParceiroUUID'))
    # OrdemID: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey('ORDENS_SERVICO.OrdemID'))
    PedidoID: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey('PEDIDOS_SERVICO.PedidoID'))
    TwilioMessageSID: Mapped[Optional[str]] = mapped_column(String(100))
    Direcao: Mapped[Optional[str]] = mapped_column(String(10))
    CorpoMensagem: Mapped[Optional[str]] = mapped_column(Unicode)
    MediaUrl_BlobPath: Mapped[Optional[str]] = mapped_column(String(500))
    DataHora: Mapped[Optional[datetime.datetime]] = mapped_column(DATETIME2, server_default=text('(getdate())'))

    # Relacionamentos
    # ordem: Mapped[Optional['OrdemServico']] = relationship(back_populates='interacoes')
    pedido: Mapped[Optional['PedidoServico']] = relationship(back_populates='interacoes')
    parceiro: Mapped[Optional['ParceiroPerfil']] = relationship(back_populates='interacoes')

# ============================================================================
# VIEWS (SOMENTE LEITURA)
# ============================================================================

class VwDashEficienciaMatch(Base):
    __tablename__ = 'VW_DASH_EFICIENCIA_MATCH'
    __table_args__ = {'info': dict(is_view=True)}
    
    # Chave primária para o SQLAlchemy
    Atividade: Mapped[str] = mapped_column(String(100), primary_key=True)
    Cidade: Mapped[str] = mapped_column(String(100), primary_key=True)
    Total_Disparos: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Aceitos: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Aceitos_Atrasado: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Negados: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Cancelados: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Pendentes: Mapped[Optional[int]] = mapped_column(Integer)
    Taxa_Conversao_Pct: Mapped[Optional[float]] = mapped_column(Float(53))
    Taxa_Interesse_Pct: Mapped[Optional[float]] = mapped_column(Float(53))
    Tempo_Medio_Aceite_Minutos: Mapped[Optional[int]] = mapped_column(Integer)

class VwParceiroDetalhado(Base):
    __tablename__ = 'VW_PARCEIRO_DETALHADO'
    __table_args__ = {'info': dict(is_view=True)}
    
    # Chave primária para o SQLAlchemy
    ParceiroUUID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    NomeCompleto: Mapped[Optional[str]] = mapped_column(String(255))
    Rua: Mapped[Optional[str]] = mapped_column(String(255))
    NumeroEndereco: Mapped[Optional[str]] = mapped_column(String(50))
    Bairro: Mapped[Optional[str]] = mapped_column(String(100))
    Cidade: Mapped[Optional[str]] = mapped_column(String(100))
    CEP: Mapped[Optional[str]] = mapped_column(String(15))
    Telefone: Mapped[Optional[str]] = mapped_column(String(50))
    Email: Mapped[Optional[str]] = mapped_column(String(255))
    CPF: Mapped[Optional[str]] = mapped_column(String(20))
    CNPJ: Mapped[Optional[str]] = mapped_column(String(20))
    StatusAtual: Mapped[Optional[str]] = mapped_column(String(20))
    DistanciaMaximaKm: Mapped[Optional[float]] = mapped_column(Float(53))
    Observacao: Mapped[Optional[str]] = mapped_column(Unicode)
    Lat: Mapped[Optional[float]] = mapped_column(Float)
    Lon: Mapped[Optional[float]] = mapped_column(Float)
    Veiculos: Mapped[Optional[str]] = mapped_column(String(100))
    HabIDs: Mapped[Optional[str]] = mapped_column(String(500))
    DispRaw: Mapped[Optional[str]] = mapped_column(String(500))
    TotalOrdensConcluidas: Mapped[Optional[int]] = mapped_column(Integer)
    OrdensUltimoMes: Mapped[Optional[int]] = mapped_column(Integer)
    TotalOrdensRecebidas: Mapped[Optional[int]] = mapped_column(Integer)
    UltimoAtendimentoData: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    UltimoAtendimentoTipo: Mapped[Optional[str]] = mapped_column(String(100))
    AvaliacaoMedia: Mapped[Optional[float]] = mapped_column(Float)

class VwBackofficeConversao(Base):
    __tablename__ = 'VW_BACKOFFICE_CONVERSAO'
    __table_args__ = {'info': dict(is_view=True)}
    
    # Chave primária para o SQLAlchemy
    Atividade: Mapped[str] = mapped_column(String(100), primary_key=True)
    Cidade: Mapped[str] = mapped_column(String(100), primary_key=True)
    Bairro: Mapped[str] = mapped_column(String(100), primary_key=True)
    Total_Disparos: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Aceitos: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Aceitos_Atrasado: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Negados: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Cancelados: Mapped[Optional[int]] = mapped_column(Integer)
    Total_Pendentes: Mapped[Optional[int]] = mapped_column(Integer)
    Taxa_Conversao_Pct: Mapped[Optional[float]] = mapped_column(Float(53))
    Taxa_Interesse_Pct: Mapped[Optional[float]] = mapped_column(Float(53))

class VwBackofficeBalanco(Base):
    __tablename__ = 'VW_BACKOFFICE_BALANCO'
    __table_args__ = {'info': dict(is_view=True)}
    
    # Chave primária para o SQLAlchemy
    Cidade: Mapped[str] = mapped_column(String(100), primary_key=True)
    Atividade: Mapped[str] = mapped_column(String(100), primary_key=True)
    Demanda_Mensal: Mapped[Optional[int]] = mapped_column(Integer)
    Oferta_Parceiros: Mapped[Optional[int]] = mapped_column(Integer)
    Indice_Pressao: Mapped[Optional[float]] = mapped_column(Float(53))  

class VwListaParceiro(Base):
    __tablename__ = 'VW_LISTA_PARCEIRO'
    __table_args__ = {'info': dict(is_view=True)}
    ParceiroUUID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    NomeCompleto: Mapped[Optional[str]] = mapped_column(String(255))
    Rua: Mapped[Optional[str]] = mapped_column(String(255))
    NumeroEndereco: Mapped[Optional[int]] = mapped_column(Integer)
    Bairro: Mapped[Optional[str]] = mapped_column(String(100))
    Cidade: Mapped[Optional[str]] = mapped_column(String(100))
    CEP: Mapped[Optional[str]] = mapped_column(String(15))
    Telefone: Mapped[Optional[str]] = mapped_column(String(50))
    CPF: Mapped[Optional[str]] = mapped_column(String(20))
    CNPJ: Mapped[Optional[str]] = mapped_column(String(20))
    StatusAtual: Mapped[Optional[str]] = mapped_column(String(20))
    DistanciaMaximaKm: Mapped[Optional[float]] = mapped_column(Float(53))
    HabIDs: Mapped[str] = mapped_column(String(255))

class VwParceiroID(Base):
    __tablename__ = 'VW_PARCEIRO_ID'
    __table_args__ = {'info': dict(is_view=True)}
    ParceiroUUID: Mapped[str] = mapped_column(String(50), primary_key=True)
    NomeCompleto: Mapped[Optional[str]] = mapped_column(String(255))
    Email: Mapped[Optional[str]] = mapped_column(String(255))
    Rua: Mapped[Optional[str]] = mapped_column(String(255))
    NumeroEndereco: Mapped[Optional[str]] = mapped_column(String(20))
    Bairro: Mapped[Optional[str]] = mapped_column(String(100))
    Cidade: Mapped[Optional[str]] = mapped_column(String(100))
    CEP: Mapped[Optional[str]] = mapped_column(String(15))
    Telefone: Mapped[Optional[str]] = mapped_column(String(50))
    CPF: Mapped[Optional[str]] = mapped_column(String(20))
    CNPJ: Mapped[Optional[str]] = mapped_column(String(20))
    StatusAtual: Mapped[Optional[str]] = mapped_column(String(20))
    DistanciaMaximaKm: Mapped[Optional[float]] = mapped_column(Float(53))
    ChavePix: Mapped[Optional[str]] = mapped_column(String(100))
    Aceite: Mapped[Optional[bool]] = mapped_column(Boolean)

# ============================================================================
# Tabelas de Agregação de OS
# ============================================================================

class OSAgrupada(Base):
    __tablename__ = 'OS_AGRUPADAS'

    AgrupamentoID: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text('(newid())'))
    NomeAgrupamento: Mapped[str] = mapped_column(String(255), nullable=False)
    Descricao: Mapped[str] = mapped_column(String(255), nullable=True)
    DataCriacao: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=text('(getdate())'))
    CriadoPor: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Relacionamentos
    vinculos_os: Mapped[List['AgrupamentoOS']] = relationship(back_populates='agrupamento')

class AgrupamentoOS(Base):
    __tablename__ = 'AGRUPAMENTO_OS'

    AgrupamentoOSPedidoID: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    AgrupamentoID: Mapped[uuid.UUID] = mapped_column(ForeignKey('OS_AGRUPADAS.AgrupamentoID'), nullable=False)
    PedidoID: Mapped[uuid.UUID] = mapped_column(ForeignKey('PEDIDOS_SERVICO.PedidoID'), nullable=False)
    EvidenciaEnviada: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('(0)'))
    DataVinculo: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=text('(getdate())'))

    # Relacionamentos
    agrupamento: Mapped['OSAgrupada'] = relationship(back_populates='vinculos_os')
    pedido: Mapped['PedidoServico'] = relationship(back_populates='agrupamentos_vinculados')
