"""add_complemento

Revision ID: f1ca5d4837c1
Revises: b3119296a232
Create Date: 2026-04-02 16:09:51.745756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1ca5d4837c1'
down_revision: Union[str, Sequence[str], None] = 'b3119296a232'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('PEDIDOS_SERVICO', sa.Column('Complemento', sa.String(length=200), nullable=True))

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('PEDIDOS_SERVICO', 'Complemento')
    # ### end Alembic commands ###
