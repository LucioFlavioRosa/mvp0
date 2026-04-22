"""add_cnpj_and_ativo_to_preco

Revision ID: b76d4095fc37
Revises: e7a8d30d4c74
Create Date: 2026-03-25 16:15:08.759337

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b76d4095fc37'
down_revision: Union[str, Sequence[str], None] = 'e7a8d30d4c74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Novas colunas CNPJ
    op.add_column('EMPRESAS', sa.Column('CNPJ', sa.String(length=20), nullable=True))
    op.add_column('FILIAIS', sa.Column('CNPJ', sa.String(length=20), nullable=True))
    op.add_column('UNIDADES', sa.Column('CNPJ', sa.String(length=20), nullable=True))
    
    # PrecoServicoUnidade status
    op.add_column('PRECOS_SERVICOS_UNIDADE', sa.Column('Ativo', sa.Boolean(), server_default=sa.text('((1))'), nullable=True))

def downgrade() -> None:
    op.drop_column('PRECOS_SERVICOS_UNIDADE', 'Ativo')
    op.drop_column('UNIDADES', 'CNPJ')
    op.drop_column('FILIAIS', 'CNPJ')
    op.drop_column('EMPRESAS', 'CNPJ')
