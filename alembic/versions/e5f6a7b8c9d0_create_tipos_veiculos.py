"""Create TIPOS_VEICULOS and add FK in PARCEIROS_VEICULOS

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-30 17:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Cria tabela TIPOS_VEICULOS com dados iniciais e adiciona FK em PARCEIROS_VEICULOS.
    """

    # 1. Criar tabela TIPOS_VEICULOS
    op.create_table('TIPOS_VEICULOS',
        sa.Column('TipoVeiculoID', sa.Integer(), sa.Identity(start=1, increment=1), nullable=False),
        sa.Column('Descricao', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('TipoVeiculoID')
    )

    # 2. Inserir dados iniciais (seed)
    op.execute("""
        SET IDENTITY_INSERT TIPOS_VEICULOS ON;
        INSERT INTO TIPOS_VEICULOS (TipoVeiculoID, Descricao) VALUES
            (1, 'Moto'),
            (2, 'Carro')
        SET IDENTITY_INSERT TIPOS_VEICULOS OFF;
    """)

    # 3. Garantir que os registros existentes em PARCEIROS_VEICULOS têm TipoVeiculoID válido
    #    (parceiros com ID fora do catálogo recebem ID 1 = Moto como fallback)
    op.execute("""
        UPDATE PARCEIROS_VEICULOS
        SET TipoVeiculoID = 1
        WHERE TipoVeiculoID NOT IN (SELECT TipoVeiculoID FROM TIPOS_VEICULOS)
    """)

    # 4. Adicionar FK em PARCEIROS_VEICULOS
    op.create_foreign_key(
        'FK_ParceiroVeiculo_TipoVeiculo',
        'PARCEIROS_VEICULOS', 'TIPOS_VEICULOS',
        ['TipoVeiculoID'], ['TipoVeiculoID']
    )


def downgrade() -> None:
    """Downgrade: remove FK e dropa TIPOS_VEICULOS."""

    op.drop_constraint('FK_ParceiroVeiculo_TipoVeiculo', 'PARCEIROS_VEICULOS', type_='foreignkey')
    op.drop_table('TIPOS_VEICULOS')
