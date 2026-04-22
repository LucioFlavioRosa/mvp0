"""Add Nome column to Servico

Revision ID: dd4d4062679b
Revises: 917c74710f72
Create Date: 2026-03-25 17:23:52.344342

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd4d4062679b'
down_revision: Union[str, Sequence[str], None] = '917c74710f72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('SERVICOS', sa.Column('Nome', sa.String(length=100), nullable=True))
    # Populate existing rows with a default if necessary (optional here since we just created it)
    # Then make it nullable=False if desired, but for safer migration I'll allow NULL or a default.
    # The model says nullable=False, so let's set a default empty string for now.
    op.execute("UPDATE SERVICOS SET Nome = ''")
    op.alter_column('SERVICOS', 'Nome', nullable=False, existing_type=sa.String(length=100))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('SERVICOS', 'Nome')
