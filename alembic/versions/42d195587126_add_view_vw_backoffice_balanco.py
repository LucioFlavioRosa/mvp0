"""add_view_vw_backoffice_balanco

Revision ID: 42d195587126
Revises: 7b8aa0cdb203
Create Date: 2026-03-23 17:20:34.238829

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '42d195587126'
down_revision: Union[str, Sequence[str], None] = '7b8aa0cdb203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE VIEW VW_BACKOFFICE_BALANCO AS
            WITH Catalogo_Unico AS (
                    SELECT DISTINCT TipoServicoID, Atividade
                    FROM CATALOGO_TIPOS_SERVICO
                ),
                DemandaRecente AS (
                    SELECT 
                        Cidade, 
                        TipoServicoID, 
                        COUNT(DISTINCT PedidoID) as Qtd_Pedidos_30dias
                    FROM PEDIDOS_SERVICO
                    WHERE DataCriacao >= DATEADD(day, -30, GETDATE())
                    GROUP BY Cidade, TipoServicoID
                ),
                OfertaAtual AS (
                    SELECT 
                        PP.Cidade, 
                        PH.TipoServicoID, 
                        COUNT(DISTINCT PP.ParceiroUUID) as Qtd_Parceiros_Habilitados
                    FROM PARCEIROS_PERFIL PP
                    JOIN CHAT_SESSIONS CS ON PP.WhatsAppID = CS.WhatsAppID
                    JOIN PARCEIROS_HABILIDADES PH ON PP.ParceiroUUID = PH.ParceiroUUID
                    WHERE CS.CurrentStep = 'FINALIZADO'
                    GROUP BY PP.Cidade, PH.TipoServicoID
                )
                SELECT 
                    COALESCE(DR.Cidade, OA.Cidade) AS Cidade,
                    CTS.Atividade,
                    ISNULL(DR.Qtd_Pedidos_30dias, 0) as Demanda_Mensal,
                    ISNULL(OA.Qtd_Parceiros_Habilitados, 0) as Oferta_Parceiros,
                    CASE 
                        WHEN ISNULL(OA.Qtd_Parceiros_Habilitados, 0) = 0 THEN 999 
                        ELSE CAST(ISNULL(DR.Qtd_Pedidos_30dias, 0) AS FLOAT) / OA.Qtd_Parceiros_Habilitados 
                    END AS Indice_Pressao
                FROM DemandaRecente DR
                FULL OUTER JOIN OfertaAtual OA 
                    ON DR.Cidade = OA.Cidade 
                    AND DR.TipoServicoID = OA.TipoServicoID
                LEFT JOIN Catalogo_Unico CTS 
                    ON CTS.TipoServicoID = COALESCE(DR.TipoServicoID, OA.TipoServicoID)
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP VIEW IF EXISTS VW_BACKOFFICE_BALANCO")
