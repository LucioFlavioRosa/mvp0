"""Add missing FKs: TipoServicoID in ParceiroHabilidade, PedidoServico, OrdemServico

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-30 17:35:00.000000

Pré-requisito: dados com TipoServicoID inválidos foram normalizados antes desta migração.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adiciona FKs ausentes apontando para CATALOGO_SERVICOS.ServicoID.
    A FK de PARCEIROS_VEICULOS -> TIPOS_VEICULOS já foi criada na Fase 5.
    """
    # PRE-CLEANUP: Point orphaned data to a valid ServicoID to preserve historical data 
    # without triggering DELETE CASCADE violations with child tables (PEDIDOS_DISPAROS)
    op.execute("""
    DECLARE @ValidID INT;
    SELECT TOP 1 @ValidID = ServicoID FROM CATALOGO_SERVICOS;

    IF @ValidID IS NULL
    BEGIN
        INSERT INTO CATALOGO_SERVICOS (CodigoServico, Nome, Descricao)
        VALUES ('MIG-DUMMY', 'Servico Dummy (Migracao)', 'Placeholder para pedidos orfaos do legado');
        
        SET @ValidID = SCOPE_IDENTITY();
    END

    UPDATE PEDIDOS_SERVICO 
    SET TipoServicoID = @ValidID 
    WHERE TipoServicoID IS NOT NULL AND TipoServicoID NOT IN (SELECT ServicoID FROM CATALOGO_SERVICOS);

    UPDATE ORDENS_SERVICO 
    SET TipoServicoID = @ValidID 
    WHERE TipoServicoID IS NOT NULL AND TipoServicoID NOT IN (SELECT ServicoID FROM CATALOGO_SERVICOS);

    DELETE FROM PARCEIROS_HABILIDADES 
    WHERE TipoServicoID IS NOT NULL AND TipoServicoID NOT IN (SELECT ServicoID FROM CATALOGO_SERVICOS);
    """)

    # FK: PARCEIROS_HABILIDADES.TipoServicoID -> CATALOGO_SERVICOS.ServicoID
    op.create_foreign_key(
        'FK_ParceiroHabilidade_Servico',
        'PARCEIROS_HABILIDADES', 'CATALOGO_SERVICOS',
        ['TipoServicoID'], ['ServicoID']
    )

    # FK: PEDIDOS_SERVICO.TipoServicoID -> CATALOGO_SERVICOS.ServicoID
    op.create_foreign_key(
        'FK_PedidoServico_Servico',
        'PEDIDOS_SERVICO', 'CATALOGO_SERVICOS',
        ['TipoServicoID'], ['ServicoID']
    )

    # FK: ORDENS_SERVICO.TipoServicoID -> CATALOGO_SERVICOS.ServicoID
    op.create_foreign_key(
        'FK_OrdemServico_Servico',
        'ORDENS_SERVICO', 'CATALOGO_SERVICOS',
        ['TipoServicoID'], ['ServicoID']
    )


def downgrade() -> None:
    """Remove as FKs adicionadas."""
    op.drop_constraint('FK_OrdemServico_Servico', 'ORDENS_SERVICO', type_='foreignkey')
    op.drop_constraint('FK_PedidoServico_Servico', 'PEDIDOS_SERVICO', type_='foreignkey')
    op.drop_constraint('FK_ParceiroHabilidade_Servico', 'PARCEIROS_HABILIDADES', type_='foreignkey')
