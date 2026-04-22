"""add_view_vw_parceiro_id

Revision ID: 4faff1819a9b
Revises: 63b43a1fb4bf
Create Date: 2026-03-24 14:00:39.296665

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4faff1819a9b'
down_revision: Union[str, Sequence[str], None] = '63b43a1fb4bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE VIEW VW_PARCEIRO_ID AS
        SELECT 
            pr.ParceiroUUID,
            COALESCE(
                pr.NomeCompleto,
                JSON_VALUE(cs.TempData, '$.nome_completo'),
                REPLACE(REPLACE(pr.WhatsAppID, 'whatsapp:+55', ''), 'whatsapp:+', ''),
                'Sem nome'
            ) AS NomeCompleto,
            ISNULL(pr.Email, '') AS Email,
            ISNULL(pr.Rua, '') AS Rua,
            ISNULL(CAST(pr.Numero AS VARCHAR), '') AS NumeroEndereco,
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
            ISNULL(pr.chave_pix, '') AS ChavePix,
            pr.Aceite
        FROM PARCEIROS_PERFIL pr
        LEFT JOIN CHAT_SESSIONS cs ON pr.WhatsAppID = cs.WhatsAppID
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP VIEW IF EXISTS VW_PARCEIRO_ID")
