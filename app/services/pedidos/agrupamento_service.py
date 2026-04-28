"""
AgrupamentoService — Domínio: Agrupamentos de OS (Lote)

Responsável pela inteligência de match coletivo e disparo em lote:
  - obter_detalhes_lote(): match de parceiros aptos para todos os serviços do lote
  - disparar_lote(): orquestração do disparo WhatsApp para múltiplos pedidos
"""

import asyncio
import uuid
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session
from sqlalchemy import select, func, distinct

from app.models import (
    PedidoServico,
    ParceiroPerfil,
    ParceiroHabilidade,
)
from app.services.pedidos.dispatch_service import DispatchService
from app.services.parceiros.parceiro_service import ParceiroService


# Coordenadas de fallback (Belém-PA) para pedidos sem georreferenciamento
_LAT_FALLBACK = -1.4558
_LNG_FALLBACK = -48.4902


class AgrupamentoService:

    # =========================================================================
    # DETALHES DO AGRUPAMENTO
    # =========================================================================

    @staticmethod
    def obter_detalhes_lote(db: Session, id_pedidos: List[str]) -> dict:
        """
        Retorna pedidos formatados e parceiros compatíveis com o lote inteiro.

        Lógica de match coletivo:
          - Identifica o conjunto de TipoServicoID únicos no lote.
          - Filtra apenas parceiros que possuam TODAS as habilidades necessárias
            (group_by + having count == total de serviços únicos).
          - Calcula a distância geodésica de cada parceiro ao centroide do agrupamento.
        """
        from sqlalchemy.orm import joinedload
        from geopy.distance import geodesic

        # --- 1. Valida e converte IDs ---
        uuids_validos = []
        for pid in id_pedidos:
            try:
                uuids_validos.append(uuid.UUID(pid))
            except ValueError:
                pass

        if not uuids_validos or len(uuids_validos) != len(id_pedidos):
            return {"error": "IDs de OS inválidos."}

        # --- 2. Busca os pedidos com tipo de serviço via ORM ---
        stmt_pedidos = (
            select(PedidoServico)
            .options(joinedload(PedidoServico.tipo_servico_ref))
            .where(PedidoServico.PedidoID.in_(uuids_validos))
            .order_by(PedidoServico.PrazoConclusaoOS, PedidoServico.Urgencia)
        )

        pedidos_db = db.execute(stmt_pedidos).scalars().all()

        pedidos_formatados = []
        lista_servicos = []
        lats = []
        lngs = []

        for p in pedidos_db:
            # Apenas pedidos AGUARDANDO podem ser agrupados
            if p.StatusPedido.upper() != "AGUARDANDO":
                return {"error": "Você não pode agrupar uma OS que já está em andamento."}

            servico_id = p.TipoServicoID
            if servico_id not in lista_servicos:
                lista_servicos.append(servico_id)

            lat = float(p.Lat) if p.Lat else _LAT_FALLBACK
            lng = float(p.Lng) if p.Lng else _LNG_FALLBACK
            lats.append(lat)
            lngs.append(lng)

            pedidos_formatados.append({
                "PedidoID": str(p.PedidoID),
                "Atividade": p.tipo_servico_ref.Nome if p.tipo_servico_ref else "Serviço Não Informado",
                "Rua": p.Rua,
                "Numero": p.Numero,
                "Bairro": p.Bairro,
                "Cidade": p.Cidade,
                "PrazoConclusaoOS": p.PrazoConclusaoOS.strftime("%d/%m/%Y %H:%M") if p.PrazoConclusaoOS else "",
                "TempoMedio": str(p.tipo_servico_ref.TempoMedioExecucao) if p.tipo_servico_ref and p.tipo_servico_ref.TempoMedioExecucao else "Não informado",
                "Urgencia": p.Urgencia,
                "StatusPedido": p.StatusPedido,
                "Lat": lat,
                "Lng": lng,
            })

        # --- 3. Centroide do agrupamento ---
        centro_lat = sum(lats) / len(lats) if lats else _LAT_FALLBACK
        centro_lng = sum(lngs) / len(lngs) if lngs else _LNG_FALLBACK

        # --- 4. Match coletivo: parceiros que possuem TODAS as habilidades do lote ---
        total_necessario = len(lista_servicos)

        subq_compativeis = (
            select(ParceiroHabilidade.ParceiroUUID)
            .where(ParceiroHabilidade.TipoServicoID.in_(lista_servicos))
            .group_by(ParceiroHabilidade.ParceiroUUID)
            .having(func.count(distinct(ParceiroHabilidade.TipoServicoID)) == total_necessario)
        )

        # Usamos STAsText() para extrair as coordenadas da coluna Geography do SQL Server
        stmt_parceiros = (
            select(
                ParceiroPerfil,
                func.STAsText(ParceiroPerfil.Geo_Base).label("wkt")
            )
            .where(
                ParceiroPerfil.ParceiroUUID.in_(subq_compativeis),
                ParceiroPerfil.StatusAtual == "ATIVO",
                ParceiroPerfil.Geo_Base.is_not(None)
            )
        )

        parceiros_db = db.execute(stmt_parceiros).all()

        # --- 5. Formata parceiros e calcula distância ao centroide ---
        parceiros_formatados = []
        for row in parceiros_db:
            p = row[0]   # Objeto ParceiroPerfil
            wkt = row[1]  # String "POINT (long lat)"
            
            uuid_str = str(p.ParceiroUUID)
            
            # Extrai lat/long do WKT: Ex "POINT (-48.5022 -1.4558)"
            try:
                # O SQL Server retorna POINT (LONG LAT)
                coords = wkt.replace("POINT (", "").replace(")", "").split()
                p_lng = float(coords[0])
                p_lat = float(coords[1])
            except Exception:
                p_lat, p_lng = _LAT_FALLBACK, _LNG_FALLBACK

            try:
                distancia = round(
                    geodesic((p_lat, p_lng), (centro_lat, centro_lng)).kilometers, 2
                )
            except Exception:
                distancia = 999.0

            parceiros_formatados.append({
                "ParceiroUUID": uuid_str,
                "NomeCompleto": p.NomeCompleto,
                "Cidade": p.Cidade,
                "TelefoneFormatado": ParceiroService._formatar_telefone(p.WhatsAppID),
                "FotoUrl": f"https://staegeadocscaddevusc.blob.core.windows.net/selfie/{uuid_str.upper()}/selfie.jpg",
                "StatusAtual": p.StatusAtual,
                "Lat": p_lat,
                "Lon": p_lng,
                "distancia": distancia,
            })

        # Ordena por proximidade ao centroide
        parceiros_formatados.sort(key=lambda x: x["distancia"])

        return {
            "pedidos": pedidos_formatados,
            "parceiros": parceiros_formatados,
            "centroide": {"lat": centro_lat, "lng": centro_lng},
            "total_pedidos": len(pedidos_formatados),
            "total_parceiros": len(parceiros_formatados),
        }

    # =========================================================================
    # DISPARO EM LOTE
    # =========================================================================

    @staticmethod
    async def disparar_lote(db: Session, id_pedidos: List[str], parceiros_selecionados: List[str]) -> dict:
        """
        Dispara convites WhatsApp para os parceiros selecionados
        em cada pedido do lote. Registra auditoria via DispatchService.

        Aguarda 0.5s entre pedidos para respeitar os limites da API Twilio.
        """
        dispatch = DispatchService()
        sucessos = 0
        falhas = 0

        for pedido_id in id_pedidos:
            try:
                resultado = dispatch.enviar_oferta_para_prestadores(
                    db, parceiros_selecionados, pedido_id
                )
                if resultado.get("status") == "success":
                    sucessos += 1
                else:
                    falhas += 1
                    print(f"❌ Falha no disparo da OS {pedido_id}: {resultado}")
            except Exception as e:
                falhas += 1
                print(f"❌ Exceção no disparo da OS {pedido_id}: {e}")

            # Pausa não bloqueante para respeitar limites da API
            await asyncio.sleep(0.5)

        if falhas == 0:
            return {
                "success": True,
                "message": f"{sucessos} demanda(s) disparada(s) com sucesso via WhatsApp!",
                "sucessos": sucessos,
                "falhas": 0,
            }

        return {
            "success": False,
            "message": f"Disparo concluído com {falhas} falha(s). {sucessos} OS(s) disparada(s).",
            "sucessos": sucessos,
            "falhas": falhas,
        }
