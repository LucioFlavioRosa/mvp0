from sqlalchemy.orm import Session, selectinload, defer
from sqlalchemy import select, literal_column
from geopy.distance import geodesic
from app.models import ParceiroPerfil, ParceiroHabilidade, ParceiroVeiculo, ParceiroDisponibilidade
from app.services.parceiros.parceiro_service import ParceiroService

# Coordenadas de fallback (Belém-PA)
_LAT_FALLBACK = -1.4558
_LNG_FALLBACK = -48.4902


class MatchParceiroService:
    @staticmethod
    def match_parceiros(
        db: Session,
        servico_id: int,
        lat_referencia: float = _LAT_FALLBACK,
        lng_referencia: float = _LNG_FALLBACK,
    ) -> list:
        # 1. Buscar parceiros aptos para o serviço usando SQLAlchemy
        base_stmt = (
            select(
                ParceiroPerfil,
                literal_column("Geo_Base.Lat").label("lat_val"),
                literal_column("Geo_Base.Long").label("lng_val")
            )
            .options(
                defer(ParceiroPerfil.Geo_Base),
                selectinload(ParceiroPerfil.habilidades).joinedload(ParceiroHabilidade.servico_ref),
                selectinload(ParceiroPerfil.disponibilidades)
            )
        )

        stmt = (
            base_stmt
            .join(ParceiroPerfil.habilidades)
            .where(
                ParceiroHabilidade.TipoServicoID == servico_id,
                ParceiroPerfil.StatusAtual == 'ATIVO'
            )
        )
        
        parceiros_db = db.execute(stmt).all()
        parceiros_final = []

        for row in parceiros_db:
            p = row[0]       # ParceiroPerfil
            p_lat = row[1]   # Latitude do banco
            p_lng = row[2]   # Longitude do banco
            uuid_str = str(p.ParceiroUUID)

            # Distancia
            distancia = None
            if p_lat is not None and p_lng is not None:
                try:
                    distancia = round(geodesic((p_lat, p_lng), (lat_referencia, lng_referencia)).kilometers, 2)
                except Exception:
                    pass

            # Formatações via ParceiroService
            tipo_doc, doc_formatado = ParceiroService._formatar_documento(p.CPF, p.CNPJ)
            nomes_hab = [h.servico_ref.Nome for h in p.habilidades if h.servico_ref]
            
            disp_list = []
            for d in p.disponibilidades:
                if d.Ativo:
                    disp_list.append({
                        "dia_id": d.DiaSemana,
                        "periodo_id": d.Periodo
                    })

            parceiros_final.append({
                "ParceiroUUID": uuid_str,
                "NomeCompleto": p.NomeCompleto,
                "TelefoneFormatado": ParceiroService._formatar_telefone(p.WhatsAppID),
                "FotoUrl": f"https://staegeadocscaddevusc.blob.core.windows.net/selfie/{uuid_str.upper()}/selfie.jpg",
                "StatusAtual": p.StatusAtual or 'ATIVO',
                "Lat": p_lat,
                "Lon": p_lng,
                "distancia": distancia,
                "HabilidadesList": nomes_hab,
                "TipoDocumento": tipo_doc,
                "DocumentoFormatado": doc_formatado,
                "DisponibilidadeList": disp_list,
            })

        # 4. Ordenar por distância
        parceiros_final.sort(key=lambda x: x['distancia'] if x['distancia'] is not None else 9999)

        return parceiros_final
