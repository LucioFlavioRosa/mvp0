"""update urgencia check constraint

Revision ID: 281c807525cc
Revises: 8e9e845ddf06
Create Date: 2026-03-26 11:42:48.868473

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '281c807525cc'
down_revision: Union[str, Sequence[str], None] = '8e9e845ddf06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop existing constraint (auto-generated name from SQL Server)
    # Note: We use a try/except or check if we want to be safe, 
    # but since we checked the name via script, we use it directly.
    op.execute("ALTER TABLE PEDIDOS_SERVICO DROP CONSTRAINT CK__PEDIDOS_S__Urgen__2EA5EC27")
    
    # Add new constraint with all valid values
    op.execute("""
        ALTER TABLE PEDIDOS_SERVICO 
        ADD CONSTRAINT CK_PEDIDOS_SERVICO_Urgencia 
        CHECK (Urgencia IN ('NORMAL', 'URGENTE', 'MAXIMA', 'ALTA', 'MEDIA', 'BAIXA', 'IMPRENSA', 'DIRETORIA', 'PROCON', 'JUIZADO', 'OUVIDORIA', 'SOCIAL'))
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE PEDIDOS_SERVICO DROP CONSTRAINT CK_PEDIDOS_SERVICO_Urgencia")
    # Restore original constraint (approximate definition)
    op.execute("""
        ALTER TABLE PEDIDOS_SERVICO 
        ADD CONSTRAINT CK__PEDIDOS_S__Urgen__2EA5EC27 
        CHECK (Urgencia IN ('ALTA', 'MEDIA', 'BAIXA'))
    """)
