"""Create SERVICOS_UNIDADES and remove Ativo from PRECOS

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-30 15:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Cria tabela SERVICOS_UNIDADES (camada de ativação) e migra coluna Ativo
    da PRECOS_SERVICOS_UNIDADE para a nova tabela.
    """

    # 1. Criar tabela SERVICOS_UNIDADES
    op.create_table('SERVICOS_UNIDADES',
        sa.Column('UnidadeID', sa.Integer(), nullable=False),
        sa.Column('ServicoID', sa.Integer(), nullable=False),
        sa.Column('Ativo', sa.Boolean(), server_default=sa.text('((1))'), nullable=True),
        sa.ForeignKeyConstraint(['UnidadeID'], ['UNIDADES.UnidadeID'], name='FK_ServicosUnidades_Unidade'),
        sa.ForeignKeyConstraint(['ServicoID'], ['CATALOGO_SERVICOS.ServicoID'], name='FK_ServicosUnidades_Servico'),
        sa.PrimaryKeyConstraint('UnidadeID', 'ServicoID')
    )

    # 2. Migrar dados existentes: cria registro de ativação para cada preço existente
    op.execute("""
        INSERT INTO SERVICOS_UNIDADES (UnidadeID, ServicoID, Ativo)
        SELECT UnidadeID, ServicoID, Ativo
        FROM PRECOS_SERVICOS_UNIDADE
    """)

    # 3. Drop default constraint e coluna Ativo de PRECOS_SERVICOS_UNIDADE
    op.execute("""
        DECLARE @df_name NVARCHAR(255);
        SELECT @df_name = d.name
        FROM sys.default_constraints d
        JOIN sys.columns c ON d.parent_column_id = c.column_id AND d.parent_object_id = c.object_id
        JOIN sys.tables t ON c.object_id = t.object_id
        WHERE t.name = 'PRECOS_SERVICOS_UNIDADE' AND c.name = 'Ativo';
        
        IF @df_name IS NOT NULL
            EXEC('ALTER TABLE PRECOS_SERVICOS_UNIDADE DROP CONSTRAINT ' + @df_name);
    """)
    op.drop_column('PRECOS_SERVICOS_UNIDADE', 'Ativo')


def downgrade() -> None:
    """Downgrade: restaura Ativo em PRECOS e dropa SERVICOS_UNIDADES."""

    # Restaurar coluna Ativo
    op.add_column('PRECOS_SERVICOS_UNIDADE',
        sa.Column('Ativo', sa.Boolean(), server_default=sa.text('((1))'), nullable=True)
    )

    # Migrar dados de volta
    op.execute("""
        UPDATE P SET P.Ativo = S.Ativo
        FROM PRECOS_SERVICOS_UNIDADE P
        JOIN SERVICOS_UNIDADES S ON P.UnidadeID = S.UnidadeID AND P.ServicoID = S.ServicoID
    """)

    # Dropar tabela
    op.drop_table('SERVICOS_UNIDADES')
