"""Add parceiro_alocado to pedido

Revision ID: h8b9c0d1e2f3
Revises: g7b8c9d0e1f2
Create Date: 2026-03-30 18:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h8b9c0d1e2f3'
down_revision: Union[str, Sequence[str], None] = 'g7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adicionar coluna ParceiroAlocadoUUID em PEDIDOS_SERVICO
    op.add_column('PEDIDOS_SERVICO', sa.Column('ParceiroAlocadoUUID', sa.Uuid(), nullable=True))
    
    # Adicionar Foreign Key
    op.create_foreign_key(
        'FK_PEDIDOS_SERVICO_PARCEIRO',
        'PEDIDOS_SERVICO', 'PARCEIROS_PERFIL',
        ['ParceiroAlocadoUUID'], ['ParceiroUUID']
    )


def downgrade() -> None:
    # Remover Foreign Key e coluna
    op.drop_constraint('FK_PEDIDOS_SERVICO_PARCEIRO', 'PEDIDOS_SERVICO', type_='foreignkey')
    op.drop_column('PEDIDOS_SERVICO', 'ParceiroAlocadoUUID')
