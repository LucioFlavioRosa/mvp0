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

from sqlalchemy.orm import Session, joinedload, selectinload, defer
from sqlalchemy import select, func, distinct, literal_column
from geopy.distance import geodesic

from app.models import (
    PedidoServico,
    ParceiroPerfil,
    ParceiroHabilidade,
    ParceiroVeiculo
)
from app.services.pedidos.dispatch_service import DispatchService
from app.services.parceiros.parceiro_service import ParceiroService
from app.services.infra.geocoding_service import GeocodingService


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
                "PrazoConclusaoOS": p.PrazoConclusaoOS,
                "TempoMedio": p.tipo_servico_ref.TempoMedioExecucao if p.tipo_servico_ref else None,
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

        stmt_parceiros = (
            select(
                ParceiroPerfil,
                literal_column("Geo_Base.Lat").label("lat_val"),
                literal_column("Geo_Base.Long").label("lng_val")
            )
            .options(
                defer(ParceiroPerfil.Geo_Base),
                selectinload(ParceiroPerfil.habilidades).joinedload(ParceiroHabilidade.servico_ref),
                selectinload(ParceiroPerfil.veiculos).joinedload(ParceiroVeiculo.tipo_veiculo),
                selectinload(ParceiroPerfil.pedidos_alocados),
                selectinload(ParceiroPerfil.disponibilidades)
            )
            .where(
                ParceiroPerfil.ParceiroUUID.in_(subq_compativeis),
                ParceiroPerfil.StatusAtual == "ATIVO"
            )
        )

        parceiros_db = db.execute(stmt_parceiros).all()

        # --- 5. Formata parceiros e calcula distância ao centroide ---
        parceiros_formatados = []
        for row in parceiros_db:
            p = row[0]       # Objeto ParceiroPerfil
            p_lat = row[1]   # Latitude extraída pelo banco (pode ser None)
            p_lng = row[2]   # Longitude extraída pelo banco (pode ser None)
            
            uuid_str = str(p.ParceiroUUID)
            
            # Fallback: Se o parceiro não tem Geo_Base, tenta geocodificar pelo endereço
            if p_lat is None or p_lng is None:
                try:
                    p_lat_geo, p_lng_geo = GeocodingService.geocodificar_endereco(
                        rua=p.Rua,
                        numero=str(p.Numero) if p.Numero else "S/N",
                        bairro=p.Bairro,
                        cidade=p.Cidade
                    )
                    if p_lat_geo is not None:
                        p_lat, p_lng = p_lat_geo, p_lng_geo
                except Exception as e:
                    print(f"⚠️ Erro ao tentar geocodificar parceiro {uuid_str}: {e}")

            # Se falhou tanto o banco quanto a geocodificação, usa o fallback padrão
            if p_lat is None or p_lng is None:
                p_lat, p_lng = _LAT_FALLBACK, _LNG_FALLBACK

            try:
                distancia = round(
                    geodesic((p_lat, p_lng), (centro_lat, centro_lng)).kilometers, 2
                )
            except Exception:
                distancia = None

            # Formatação de campos complexos reutilizando o ParceiroService
            tipo_doc, doc_formatado = ParceiroService._formatar_documento(p.CPF, p.CNPJ)
            nomes_hab = [h.servico_ref.Nome for h in p.habilidades if h.servico_ref]
            veiculos_str = ", ".join([
                v.tipo_veiculo.NomeVeiculo for v in p.veiculos if v.tipo_veiculo and v.Ativo
            ]) or "Nenhum"
            
            disp_list = [
                {"dia_id": d.DiaSemana, "periodo_id": d.Periodo}
                for d in p.disponibilidades if d.Ativo
            ]

            parceiros_formatados.append({
                "ParceiroUUID": uuid_str,
                "NomeCompleto": p.NomeCompleto,
                "Cidade": p.Cidade,
                "Bairro": p.Bairro,
                "Rua": p.Rua,
                "Numero": str(p.Numero) if p.Numero else "S/N",
                "TelefoneFormatado": ParceiroService._formatar_telefone(p.WhatsAppID),
                "Email": p.Email,
                "FotoUrl": f"https://staegeadocscaddevusc.blob.core.windows.net/selfie/{uuid_str.upper()}/selfie.jpg",
                "StatusAtual": p.StatusAtual or 'ATIVO',
                "Lat": p_lat,
                "Lon": p_lng,
                "distancia": distancia,
                "Veiculos": veiculos_str,
                "HabilidadesList": nomes_hab,
                "TipoDocumento": tipo_doc,
                "DocumentoFormatado": doc_formatado,
                "DistanciaMaximaKm": p.DistanciaMaximaKm,
                "TotalOrdensConcluidas": len([o for o in p.pedidos_alocados if o.StatusPedido == 'CONCLUIDO']),
                "DisponibilidadeList": disp_list
            })

        # Ordena por proximidade ao centroide
        parceiros_formatados.sort(key=lambda x: x["distancia"] if x["distancia"] is not None else 9999)

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
