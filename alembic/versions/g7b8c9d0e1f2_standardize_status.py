"""Standardize status and add CHECK constraints

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-30 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Normalizar dados existentes (Casing)
    op.execute("UPDATE PARCEIROS_PERFIL SET StatusAtual = 'EM_ANALISE' WHERE StatusAtual = 'Em_analise'")
    op.execute("UPDATE PARCEIROS_PERFIL SET StatusAtual = 'ATIVO' WHERE StatusAtual = 'Ativo'")
    
    # 2. Adicionar CHECK constraints
    # SQL Server syntax: ALTER TABLE T ADD CONSTRAINT CK_Name CHECK (Col IN ('A', 'B'))

    # PARCEIROS_PERFIL
    op.execute("""
        ALTER TABLE PARCEIROS_PERFIL 
        ADD CONSTRAINT CK_Parceiro_Status 
        CHECK (StatusAtual IN ('ATIVO', 'INATIVO', 'EM_ANALISE', 'SUSPENSO', 'PENDENTE'))
    """)

    # PEDIDOS_SERVICO
    op.execute("""
        ALTER TABLE PEDIDOS_SERVICO 
        ADD CONSTRAINT CK_Pedido_Status 
        CHECK (StatusPedido IN ('AGUARDANDO', 'VINCULADO', 'CANCELADO', 'FINALIZADO'))
    """)

    # ORDENS_SERVICO
    op.execute("""
        ALTER TABLE ORDENS_SERVICO 
        ADD CONSTRAINT CK_Ordem_Status 
        CHECK (StatusOrdem IN ('ABERTA', 'EM_EXECUCAO', 'CONCLUIDA', 'CANCELADA'))
    """)


def downgrade() -> None:
    # Remover constraints
    op.execute("ALTER TABLE ORDENS_SERVICO DROP CONSTRAINT CK_Ordem_Status")
    op.execute("ALTER TABLE PEDIDOS_SERVICO DROP CONSTRAINT CK_Pedido_Status")
    op.execute("ALTER TABLE PARCEIROS_PERFIL DROP CONSTRAINT CK_Parceiro_Status")
