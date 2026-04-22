"""Consolidate CATALOGO_SERVICOS and drop CATALOGO_TIPOS_SERVICO

Revision ID: a1b2c3d4e5f6
Revises: 281c807525cc
Create Date: 2026-03-30 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '281c807525cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Consolida CATALOGO_SERVICOS como fonte única de verdade.
    - Reescreve VW_BACKOFFICE_CONVERSAO usando CATALOGO_SERVICOS
    - Reescreve VW_BACKOFFICE_BALANCO usando CATALOGO_SERVICOS
    - Dropa CATALOGO_TIPOS_SERVICO (tabela vazia, legada da POC)
    """

    # 1. Drop e recria VW_BACKOFFICE_CONVERSAO
    op.execute("DROP VIEW IF EXISTS VW_BACKOFFICE_CONVERSAO")
    op.execute("""
        CREATE VIEW VW_BACKOFFICE_CONVERSAO AS
            WITH Pedidos_Unicos AS (
                SELECT DISTINCT PedidoID, Cidade, Bairro, TipoServicoID, DataCriacao
                FROM PEDIDOS_SERVICO
            ),
            Catalogo_Unico AS (
                SELECT DISTINCT ServicoID, Nome
                FROM CATALOGO_SERVICOS
            )
            SELECT 
                T.Nome AS Atividade,
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
            JOIN Catalogo_Unico T ON P.TipoServicoID = T.ServicoID
            GROUP BY T.Nome, P.Cidade, P.Bairro
    """)

    # 2. Drop e recria VW_BACKOFFICE_BALANCO
    op.execute("DROP VIEW IF EXISTS VW_BACKOFFICE_BALANCO")
    op.execute("""
        CREATE VIEW VW_BACKOFFICE_BALANCO AS
            WITH Catalogo_Unico AS (
                    SELECT DISTINCT ServicoID, Nome
                    FROM CATALOGO_SERVICOS
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
                    CTS.Nome AS Atividade,
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
                    ON CTS.ServicoID = COALESCE(DR.TipoServicoID, OA.TipoServicoID)
    """)

    # 3. Drop FK constraints que referenciam CATALOGO_TIPOS_SERVICO
    #    SERVICOS_UNIDADES_MATERIAIS.ServicoItemID -> CATALOGO_TIPOS_SERVICO.ServicoItemID
    op.execute("""
        DECLARE @fk_name NVARCHAR(255);
        SELECT @fk_name = fk.name
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
        JOIN sys.tables t ON fkc.parent_object_id = t.object_id
        JOIN sys.tables rt ON fkc.referenced_object_id = rt.object_id
        WHERE t.name = 'SERVICOS_UNIDADES_MATERIAIS'
          AND rt.name = 'CATALOGO_TIPOS_SERVICO';
        
        IF @fk_name IS NOT NULL
            EXEC('ALTER TABLE SERVICOS_UNIDADES_MATERIAIS DROP CONSTRAINT ' + @fk_name);
    """)

    # 4. Drop tabela legada (vazia)
    op.execute("DROP TABLE IF EXISTS CATALOGO_TIPOS_SERVICO")


def downgrade() -> None:
    """Downgrade: recria a tabela legada e restaura Views originais."""

    # Recria tabela legada
    op.create_table('CATALOGO_TIPOS_SERVICO',
        sa.Column('TipoServicoID', sa.Integer(), sa.Identity(always=False, start=1, increment=1), nullable=False),
        sa.Column('Atividade', sa.String(length=100), nullable=True),
        sa.Column('TipoVeiculo', sa.String(length=50), nullable=True),
        sa.Column('EPI', sa.String(length=50), nullable=True),
        sa.Column('Perfil', sa.String(length=50), nullable=True),
        sa.Column('FormularioResposta', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('TipoServicoID')
    )

    # Restaura Views originais
    op.execute("DROP VIEW IF EXISTS VW_BACKOFFICE_CONVERSAO")
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

    op.execute("DROP VIEW IF EXISTS VW_BACKOFFICE_BALANCO")
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
