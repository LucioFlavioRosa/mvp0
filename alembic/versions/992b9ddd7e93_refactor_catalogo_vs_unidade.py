"""Refactor Catalogo vs Unidade

Revision ID: 992b9ddd7e93
Revises: dd4d4062679b
Create Date: 2026-03-25 18:07:47.297883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '992b9ddd7e93'
down_revision: Union[str, Sequence[str], None] = 'dd4d4062679b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Remover tabelas antigas para evitar conflitos de FK e nomes
    op.execute("IF OBJECT_ID('SERVICOS', 'U') IS NOT NULL DROP TABLE SERVICOS")
    op.execute("IF OBJECT_ID('PRECOS_SERVICOS_UNIDADE', 'U') IS NOT NULL DROP TABLE PRECOS_SERVICOS_UNIDADE")

    # Criar Catálogo Geral (Template)
    op.create_table('CATALOGO_SERVICOS',
        sa.Column('ServicoID', sa.Integer(), sa.Identity(always=False, start=1, increment=1), nullable=False),
        sa.Column('CodigoServico', sa.String(length=50), nullable=False),
        sa.Column('Nome', sa.String(length=100), nullable=False),
        sa.Column('Descricao', sa.String(length=200), nullable=False),
        sa.Column('TipoVeiculo', sa.String(length=50), nullable=True),
        sa.Column('EPI', sa.String(length=10), nullable=True),
        sa.Column('Perfil', sa.String(length=50), nullable=True),
        sa.Column('FormularioResposta', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('ServicoID')
    )

    # Criar Precificação por Unidade (Mapping)
    op.create_table('PRECOS_SERVICOS_UNIDADE',
        sa.Column('UnidadeID', sa.Integer(), nullable=False),
        sa.Column('ServicoID', sa.Integer(), nullable=False),
        sa.Column('Preco', sa.Float(precision=53), server_default=sa.text('0.0'), nullable=False),
        sa.Column('TempoMedioExecucao', sa.Float(), nullable=True),
        sa.Column('TempoMaximo', sa.Float(), nullable=True),
        sa.Column('FatorExtra', sa.Float(), server_default=sa.text('1.0'), nullable=True),
        sa.Column('Ativo', sa.Boolean(), server_default=sa.text('1'), nullable=True),
        sa.ForeignKeyConstraint(['ServicoID'], ['CATALOGO_SERVICOS.ServicoID'], ),
        sa.ForeignKeyConstraint(['UnidadeID'], ['UNIDADES.UnidadeID'], ),
        sa.PrimaryKeyConstraint('UnidadeID', 'ServicoID')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('PRECOS_SERVICOS_UNIDADE')
    op.drop_table('CATALOGO_SERVICOS')
