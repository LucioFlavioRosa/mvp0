"""Adjust PedidoServico columns: remove Atividade, rename DataLimite, add new columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-30 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Ajusta colunas do PEDIDOS_SERVICO:
    - Remove Atividade (será resolvido via JOIN com CATALOGO_SERVICOS)
    - Renomeia DataLimite -> PrazoConclusaoOS
    - Adiciona DataAberturaSCAE (datetime, nullable)
    - Adiciona Bloco (varchar 50, nullable)
    """

    # 1. Remover coluna Atividade
    op.drop_column('PEDIDOS_SERVICO', 'Atividade')

    # 2. Renomear DataLimite -> PrazoConclusaoOS
    op.execute("EXEC sp_rename 'PEDIDOS_SERVICO.DataLimite', 'PrazoConclusaoOS', 'COLUMN'")

    # 3. Adicionar novas colunas
    op.add_column('PEDIDOS_SERVICO', sa.Column('DataAberturaSCAE', sa.DateTime(), nullable=True))
    op.add_column('PEDIDOS_SERVICO', sa.Column('Bloco', sa.String(50), nullable=True))


def downgrade() -> None:
    """Downgrade: restaura colunas originais."""

    # Remover colunas novas
    op.drop_column('PEDIDOS_SERVICO', 'Bloco')
    op.drop_column('PEDIDOS_SERVICO', 'DataAberturaSCAE')

    # Renomear PrazoConclusaoOS de volta para DataLimite
    op.execute("EXEC sp_rename 'PEDIDOS_SERVICO.PrazoConclusaoOS', 'DataLimite', 'COLUMN'")

    # Restaurar coluna Atividade
    op.add_column('PEDIDOS_SERVICO', sa.Column('Atividade', sa.String(100), nullable=True))
