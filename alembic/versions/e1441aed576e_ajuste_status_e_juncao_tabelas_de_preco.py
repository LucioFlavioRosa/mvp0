"""Ajuste Status E Juncao Tabelas de Preco

Revision ID: e1441aed576e
Revises: c8f9bdd24318
Create Date: 2026-04-10 17:28:10.972046

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision: str = 'e1441aed576e'
down_revision: Union[str, Sequence[str], None] = 'c8f9bdd24318'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Status Migration
    op.execute("UPDATE PEDIDOS_SERVICO SET StatusPedido = 'AGUARDANDO' WHERE StatusPedido = 'AGRUPADO'")
    op.execute("ALTER TABLE PEDIDOS_SERVICO DROP CONSTRAINT CK_Pedido_Status")
    op.execute("""
        ALTER TABLE PEDIDOS_SERVICO ADD CONSTRAINT CK_Pedido_Status 
        CHECK (StatusPedido IN ('FINALIZADO', 'CANCELADO', 'VINCULADO', 'AGUARDANDO', 'DISPARADO'))
    """)

    # Merge ServicosUnidade into PrecoServicoUnidade
    op.add_column('PRECOS_SERVICOS_UNIDADE', sa.Column('Ativo', sa.Boolean(), server_default=sa.text('((1))'), nullable=True))
    
    # Migrate data
    op.execute("""
        UPDATE P
        SET P.Ativo = S.Ativo
        FROM PRECOS_SERVICOS_UNIDADE P
        INNER JOIN SERVICOS_UNIDADES S ON P.UnidadeID = S.UnidadeID AND P.ServicoID = S.ServicoID
    """)
    op.execute("""
        INSERT INTO PRECOS_SERVICOS_UNIDADE (UnidadeID, ServicoID, Preco, FatorExtra, Ativo)
        SELECT S.UnidadeID, S.ServicoID, 0.0, 1.0, S.Ativo
        FROM SERVICOS_UNIDADES S
        WHERE NOT EXISTS (
            SELECT 1 FROM PRECOS_SERVICOS_UNIDADE P 
            WHERE P.UnidadeID = S.UnidadeID AND P.ServicoID = S.ServicoID
        )
    """)
    
    op.drop_table('SERVICOS_UNIDADES')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('SERVICOS_UNIDADES',
    sa.Column('UnidadeID', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('ServicoID', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('Ativo', mssql.BIT(), server_default=sa.text('((1))'), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['ServicoID'], ['CATALOGO_SERVICOS.ServicoID'], name='FK_ServicosUnidades_Servico'),
    sa.ForeignKeyConstraint(['UnidadeID'], ['UNIDADES.UnidadeID'], name='FK_ServicosUnidades_Unidade'),
    sa.PrimaryKeyConstraint('UnidadeID', 'ServicoID', name='PK_Servicos_Unidades')
    )

    op.execute("""
        UPDATE S
        SET S.Ativo = P.Ativo
        FROM SERVICOS_UNIDADES S
        INNER JOIN PRECOS_SERVICOS_UNIDADE P ON P.UnidadeID = S.UnidadeID AND P.ServicoID = S.ServicoID
    """)

    op.drop_column('PRECOS_SERVICOS_UNIDADE', 'Ativo')

    # Status Downgrade
    op.execute("UPDATE PEDIDOS_SERVICO SET StatusPedido = 'AGUARDANDO' WHERE StatusPedido = 'DISPARADO'")
    op.execute("ALTER TABLE PEDIDOS_SERVICO DROP CONSTRAINT CK_Pedido_Status")
    op.execute("""
        ALTER TABLE PEDIDOS_SERVICO ADD CONSTRAINT CK_Pedido_Status 
        CHECK (StatusPedido IN ('FINALIZADO', 'CANCELADO', 'VINCULADO', 'AGUARDANDO', 'AGRUPADO'))
    """)
