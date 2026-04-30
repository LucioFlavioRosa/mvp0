from enum import Enum

class StatusPedido(str, Enum):
    AGUARDANDO = "AGUARDANDO"
    DISPARADO = "DISPARADO"
    VINCULADO = "VINCULADO"
    FINALIZADO = "FINALIZADO"
    CANCELADO = "CANCELADO"

class UrgenciaPedido(str, Enum):
    # Administrativas / Especiais
    SOCIAL = "SOCIAL"
    OUVIDORIA = "OUVIDORIA"
    JUIZADO = "JUIZADO"
    PROCON = "PROCON"
    DIRETORIA = "DIRETORIA"
    IMPRENSA = "IMPRENSA"
    
    # Níveis de Prioridade
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    MAXIMA = "MAXIMA"
    URGENTE = "URGENTE"
    NORMAL = "NORMAL"

class StatusParceiro(str, Enum):
    ATIVO = "ATIVO"
    INATIVO = "INATIVO"
    SUSPENSO = "SUSPENSO"
    EM_ANALISE = "EM_ANALISE"
    PENDENTE = "PENDENTE"
