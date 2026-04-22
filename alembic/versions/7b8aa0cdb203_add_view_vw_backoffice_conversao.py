"""add_view_vw_backoffice_conversao

Revision ID: 7b8aa0cdb203
Revises: b300e39d5a4d
Create Date: 2026-03-23 16:07:08.465824

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b8aa0cdb203'
down_revision: Union[str, Sequence[str], None] = 'b300e39d5a4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE VIEW VW_BACKOFFICE_CONVERSAO AS
            WITH Pedidos_Unicos AS (
                SELECT DISTINCT PedidoID, Cidade, Bairro, TipoServicoID, DataCriacao
                FROM PEDIDOS_SERVICO
            ),
            Catalogo_Unico AS (
                SELECT DISTINCT TipoServicoID, Atividade
                FROM CATALOGO_TIPOS_SERVICO
            )
            SELECT 
                T.Atividade,
                P.Cidade,
                P.Bairro,
                COUNT(D.DisparoID) AS Total_Disparos,
                SUM(CASE WHEN D.Status = 'ACEITO' THEN 1 ELSE 0 END) AS Total_Aceitos,
                SUM(CASE WHEN D.Status = 'ACEITO_ATRASADO' THEN 1 ELSE 0 END) AS Total_Aceitos_Atrasado,
                SUM(CASE WHEN D.Status = 'NEGADO' THEN 1 ELSE 0 END) AS Total_Negados,
                SUM(CASE WHEN D.Status = 'CANCELADO' THEN 1 ELSE 0 END) AS Total_Cancelados,
                SUM(CASE WHEN D.Status = 'ENVIADO' THEN 1 ELSE 0 END) AS Total_Pendentes,
                CAST(SUM(CASE WHEN D.Status = 'ACEITO' THEN 1 ELSE 0 END) AS FLOAT) 
                    / NULLIF(COUNT(D.DisparoID), 0) * 100 AS Taxa_Conversao_Pct,
                CAST(SUM(CASE WHEN D.Status IN ('ACEITO', 'ACEITO_ATRASADO') THEN 1 ELSE 0 END) AS FLOAT) 
                    / NULLIF(COUNT(D.DisparoID), 0) * 100 AS Taxa_Interesse_Pct
            FROM PEDIDOS_DISPAROS D
            JOIN Pedidos_Unicos P ON D.PedidoID = P.PedidoID
            JOIN Catalogo_Unico T ON P.TipoServicoID = T.TipoServicoID
            GROUP BY T.Atividade, P.Cidade, P.Bairro
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP VIEW IF EXISTS VW_BACKOFFICE_CONVERSAO")
