"""
BackofficeService — Domínio: Métricas, KPIs e Cobertura Geográfica

Responsável por toda a inteligência analítica do sistema:
  - obter_dashboard(): KPIs de conversão e balanço demanda vs oferta
  - verificar_cobertura(): geocoding + query espacial de parceiros aptos
"""

from sqlalchemy.orm import Session
from sqlalchemy import select, text
from app.services.infra.geocoding_service import GeocodingService


class BackofficeService:

    # =========================================================================
    # DASHBOARD GERAL (KPIs)
    # =========================================================================

    @staticmethod
    def obter_dashboard(db: Session) -> dict:
        """
        Retorna os dados consolidados para a tela de Backoffice:
        - kpi_conversao: métricas por Atividade/Cidade/Bairro (via VW_BACKOFFICE_CONVERSAO)
        - kpi_balanco: demanda vs oferta por Cidade/Atividade (via VW_BACKOFFICE_BALANCO)
        - totalizadores: somatórios calculados no Backend (elimina cálculo manual no Portal)
        """
        from app.models import VwBackofficeConversao, VwBackofficeBalanco

        # --- 1. Métricas de Conversão ---
        conversao_rows = db.execute(
            select(VwBackofficeConversao)
        ).scalars().all()

        kpi_conversao = [
            {
                "Atividade": r.Atividade,
                "Cidade": r.Cidade,
                "Bairro": r.Bairro,
                "Total_Disparos": r.Total_Disparos or 0,
                "Total_Aceitos": r.Total_Aceitos or 0,
                "Total_Aceitos_Atrasado": r.Total_Aceitos_Atrasado or 0,
                "Total_Negados": r.Total_Negados or 0,
                "Total_Cancelados": r.Total_Cancelados or 0,
                "Total_Pendentes": r.Total_Pendentes or 0,
                "Taxa_Conversao_Pct": round(r.Taxa_Conversao_Pct or 0.0, 1),
                "Taxa_Interesse_Pct": round(r.Taxa_Interesse_Pct or 0.0, 1),
            }
            for r in conversao_rows
        ]

        # --- 2. Totalizadores (calculados no Backend, não no Portal) ---
        total_disparos = sum(k["Total_Disparos"] for k in kpi_conversao)
        total_aceitos = sum(k["Total_Aceitos"] for k in kpi_conversao)
        total_negados = sum(k["Total_Negados"] for k in kpi_conversao)
        taxa_media = round(total_aceitos / total_disparos * 100, 1) if total_disparos > 0 else 0.0

        # --- 3. Balanço Demanda vs Oferta ---
        balanco_rows = db.execute(
            select(VwBackofficeBalanco)
        ).scalars().all()

        kpi_balanco = [
            {
                "Cidade": r.Cidade,
                "Atividade": r.Atividade,
                "Demanda_Mensal": r.Demanda_Mensal or 0,
                "Oferta_Parceiros": r.Oferta_Parceiros or 0,
                "Indice_Pressao": round(r.Indice_Pressao or 0.0, 1),
            }
            for r in balanco_rows
        ]

        return {
            "totalizadores": {
                "total_disparos": total_disparos,
                "total_aceitos": total_aceitos,
                "total_negados": total_negados,
                "taxa_media": taxa_media,
            },
            "kpi_conversao": kpi_conversao,
            "kpi_balanco": kpi_balanco,
        }

    # =========================================================================
    # VERIFICADOR DE COBERTURA GEOGRÁFICA
    # =========================================================================

    @staticmethod
    def verificar_cobertura(db: Session, endereco: str) -> dict:
        """
        Recebe um endereço textual, geocodifica via GeocodingService e verifica
        quantos parceiros habilitados cobrem aquele ponto por tipo de serviço.

        Retorna:
            - coordenadas: {lat, lng} do ponto geocodificado
            - cobertura: lista de {Atividade, Parceiros_Disponiveis}
        """
        # --- 1. Geocoding: delega ao GeocodingService centralizado ---
        lat, lng = GeocodingService.geocodificar_texto(endereco)

        if lat is None or lng is None:
            return {
                "coordenadas": None,
                "cobertura": [],
                "error": "Não foi possível localizar o endereço informado."
            }

        # --- 2. Query espacial: parceiros cujo raio cobre o ponto ---
        # Usa STDistance do SQL Server (distância em metros) comparada com DistanciaMaximaKm
        sql = text("""
            SELECT
                cs.Nome AS Atividade,
                COUNT(DISTINCT pp.ParceiroUUID) AS Parceiros_Disponiveis
            FROM PARCEIROS_PERFIL pp
            JOIN PARCEIROS_HABILIDADES ph ON pp.ParceiroUUID = ph.ParceiroUUID
            JOIN CATALOGO_SERVICOS cs ON ph.TipoServicoID = cs.ServicoID
            WHERE
                pp.StatusAtual = 'ATIVO'
                AND pp.Geo_Base IS NOT NULL
                AND pp.DistanciaMaximaKm IS NOT NULL
                AND (pp.Geo_Base.STDistance(geography::Point(:lat, :lng, 4326)) / 1000.0) <= pp.DistanciaMaximaKm
            GROUP BY cs.Nome
            ORDER BY cs.Nome
        """)

        rows = db.execute(sql, {"lat": lat, "lng": lng}).fetchall()

        cobertura = [
            {"Atividade": row[0], "Parceiros_Disponiveis": row[1]}
            for row in rows
        ]

        return {
            "coordenadas": {"lat": lat, "lng": lng},
            "cobertura": cobertura,
        }


