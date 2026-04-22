"""Rename ServicoItemID to ServicoID in SERVICOS_UNIDADES_MATERIAIS

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-30 16:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Renomeia ServicoItemID -> ServicoID em SERVICOS_UNIDADES_MATERIAIS
    para alinhar a FK com CATALOGO_SERVICOS.ServicoID.
    
    Depende da Fase 1 (CATALOGO_TIPOS_SERVICO já dropada).
    A PK composta precisa ser recriada com o novo nome.
    """

    # 1. Dropar constraint PK (composta contém a coluna renomeada)
    op.execute("""
        DECLARE @pk_name NVARCHAR(255);
        SELECT @pk_name = kc.name
        FROM sys.key_constraints kc
        JOIN sys.tables t ON kc.parent_object_id = t.object_id
        WHERE t.name = 'SERVICOS_UNIDADES_MATERIAIS' AND kc.type = 'PK';

        IF @pk_name IS NOT NULL
            EXEC('ALTER TABLE SERVICOS_UNIDADES_MATERIAIS DROP CONSTRAINT ' + @pk_name);
    """)

    # 2. Renomear coluna
    op.execute("EXEC sp_rename 'SERVICOS_UNIDADES_MATERIAIS.ServicoItemID', 'ServicoID', 'COLUMN'")

    # 3. Recriar PK com nome correto
    op.execute("""
        ALTER TABLE SERVICOS_UNIDADES_MATERIAIS
        ADD CONSTRAINT PK_ServicosUnidadesMateriais
        PRIMARY KEY (UnidadeID, ServicoID, MaterialID)
    """)

    # 4. Adicionar FK para CATALOGO_SERVICOS
    op.execute("""
        ALTER TABLE SERVICOS_UNIDADES_MATERIAIS
        ADD CONSTRAINT FK_SUM_Servico
        FOREIGN KEY (ServicoID) REFERENCES CATALOGO_SERVICOS(ServicoID)
    """)


def downgrade() -> None:
    """Downgrade: reverte renomeação."""

    # Drop FK e PK nova
    op.execute("ALTER TABLE SERVICOS_UNIDADES_MATERIAIS DROP CONSTRAINT FK_SUM_Servico")
    op.execute("ALTER TABLE SERVICOS_UNIDADES_MATERIAIS DROP CONSTRAINT PK_ServicosUnidadesMateriais")

    # Renomear de volta
    op.execute("EXEC sp_rename 'SERVICOS_UNIDADES_MATERIAIS.ServicoID', 'ServicoItemID', 'COLUMN'")

    # Recriar PK original
    op.execute("""
        ALTER TABLE SERVICOS_UNIDADES_MATERIAIS
        ADD CONSTRAINT PK_ServicosUnidadesMateriais
        PRIMARY KEY (UnidadeID, ServicoItemID, MaterialID)
    """)
