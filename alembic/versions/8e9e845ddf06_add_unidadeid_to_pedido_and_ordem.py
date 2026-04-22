"""Add UnidadeID to Pedido and Ordem

Revision ID: 8e9e845ddf06
Revises: 992b9ddd7e93
Create Date: 2026-03-25 18:37:27.373507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = '8e9e845ddf06'
down_revision: Union[str, Sequence[str], None] = '992b9ddd7e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ORDENS_SERVICO', sa.Column('UnidadeID', sa.Integer(), nullable=True))
    op.create_foreign_key('FK_Ordens_Unidade', 'ORDENS_SERVICO', 'UNIDADES', ['UnidadeID'], ['UnidadeID'])
    op.add_column('PEDIDOS_SERVICO', sa.Column('UnidadeID', sa.Integer(), nullable=True))
    # mssql requires a name for the constraint if we want to drop it easily later, or let alembic handle it but usually better to name it
    op.create_foreign_key('FK_Pedidos_Unidade', 'PEDIDOS_SERVICO', 'UNIDADES', ['UnidadeID'], ['UnidadeID'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('FK_Pedidos_Unidade', 'PEDIDOS_SERVICO', type_='foreignkey')
    op.drop_column('PEDIDOS_SERVICO', 'UnidadeID')
    op.drop_constraint('FK_Ordens_Unidade', 'ORDENS_SERVICO', type_='foreignkey')
    op.drop_column('ORDENS_SERVICO', 'UnidadeID')
    # ### end Alembic commands ###
