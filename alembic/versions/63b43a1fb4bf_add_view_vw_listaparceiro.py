"""add_view_vw_listaparceiro

Revision ID: 63b43a1fb4bf
Revises: 42d195587126
Create Date: 2026-03-24 10:35:59.384161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '63b43a1fb4bf'
down_revision: Union[str, Sequence[str], None] = '42d195587126'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE VIEW VW_LISTA_PARCEIRO AS
        SELECT 
            pr.ParceiroUUID,
            COALESCE(
                pr.NomeCompleto,
                JSON_VALUE(cs.TempData, '$.nome_completo'),
                REPLACE(REPLACE(pr.WhatsAppID, 'whatsapp:+55', ''), 'whatsapp:+', ''),
                'Sem nome'
            ) AS NomeCompleto,
            ISNULL(pr.Rua, '') AS Rua,
            ISNULL(pr.Numero, '') AS NumeroEndereco,
            ISNULL(pr.Bairro, '') AS Bairro,
            ISNULL(pr.Cidade, '') AS Cidade,
            ISNULL(pr.CEP, '') AS CEP,
            ISNULL(
                CASE 
                    WHEN pr.WhatsAppID IS NOT NULL THEN 
                        REPLACE(REPLACE(pr.WhatsAppID, 'whatsapp:+55', ''), 'whatsapp:+', '')
                    ELSE NULL 
                END, 
                ''
            ) AS Telefone,
            ISNULL(pr.CPF, '') AS CPF,
            ISNULL(pr.CNPJ, '') AS CNPJ,
            ISNULL(pr.StatusAtual, 'ATIVO') AS StatusAtual,
            ISNULL(pr.DistanciaMaximaKm, 0) AS DistanciaMaximaKm,
            ISNULL((
                SELECT STRING_AGG(CAST(ph.TipoServicoID AS VARCHAR), ',') 
                FROM PARCEIROS_HABILIDADES ph 
                WHERE ph.ParceiroUUID = pr.ParceiroUUID
            ), '') AS HabIDs
        FROM PARCEIROS_PERFIL pr
        LEFT JOIN CHAT_SESSIONS cs ON pr.WhatsAppID = cs.WhatsAppID
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        DROP VIEW IF EXISTS VW_LISTA_PARCEIRO
    """)