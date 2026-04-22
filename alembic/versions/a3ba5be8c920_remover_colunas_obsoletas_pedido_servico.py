"""remover_colunas_obsoletas_pedido_servico

Revision ID: a3ba5be8c920
Revises: h8b9c0d1e2f3
Create Date: 2026-03-31 11:55:05.759214

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = 'a3ba5be8c920'
down_revision: Union[str, Sequence[str], None] = 'h8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    op.drop_column('PEDIDOS_SERVICO', 'ServicoItemID')
    op.drop_column('PEDIDOS_SERVICO', 'SubAtividade')

    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    
    op.add_column('PEDIDOS_SERVICO', sa.Column('SubAtividade', sa.VARCHAR(length=100, collation='SQL_Latin1_General_CP1_CI_AS'), autoincrement=False, nullable=True))
    op.add_column('PEDIDOS_SERVICO', sa.Column('ServicoItemID', sa.INTEGER(), autoincrement=False, nullable=True))
    
    # ### end Alembic commands ###
