from sqlalchemy.orm import Session
from sqlalchemy import select
from geopy.distance import geodesic

from app.models import VwParceiroDetalhado, CatalogoServico
from app.schemas.pedido import formatar_telefone, formatar_documento, gerar_url_foto


# Mapeamentos fixos de formatação
_STATUS_DESC = {
    'ATIVO': {'label': 'Ativo', 'color': 'success'},
    'INATIVO': {'label': 'Inativo', 'color': 'danger'},
    'EM_ANALISE': {'label': 'Em Análise', 'color': 'warning'},
    'SUSPENSO': {'label': 'Suspenso', 'color': 'danger'},
}
_DIAS_DESC = {0: 'Seg', 1: 'Ter', 2: 'Qua', 3: 'Qui', 4: 'Sex', 5: 'Sáb', 6: 'Dom'}
_PERIODOS_DESC = {1: 'Manhã', 2: 'Tarde', 3: 'Noite'}

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
        """
        Retorna a lista de parceiros aptos para um determinado serviço,
        ordenados por distância em relação ao ponto de referência.

        Passos:
          1. Busca parceiros aptos via VW_PARCEIRO_DETALHADO filtrado por HabIDs.
          2. Calcula a distância geodésica (geopy) de cada parceiro ao ponto de referência.
          3. Enriquece os dados (telefone, documento, habilidades, disponibilidade).
          4. Ordena por distância (ascendente).
        """
        ts_id_str = str(servico_id)

        # 1. Buscar parceiros aptos para o serviço (via coluna HabIDs da View)
        stmt = (
            select(VwParceiroDetalhado)
            .where(VwParceiroDetalhado.HabIDs.contains(ts_id_str))
        )
        parceiros_obj = db.execute(stmt).scalars().all()
        parceiros = [p.to_dict() for p in parceiros_obj]

        # 2. Carregar catálogo de serviços para tradução de habilidades
        cat_result = db.execute(select(CatalogoServico.ServicoID, CatalogoServico.Nome)).all()
        catalogo_desc = {r.ServicoID: r.Nome for r in cat_result}

        # 3. Enriquecer cada parceiro
        for p in parceiros:
            # Distância geodésica
            if p.get('Lat') and p.get('Lon'):
                try:
                    p['distancia'] = round(
                        geodesic(
                            (float(p['Lat']), float(p['Lon'])),
                            (lat_referencia, lng_referencia)
                        ).kilometers, 2
                    )
                except Exception:
                    p['distancia'] = 999.0
            else:
                p['distancia'] = 999.0

            # Foto
            p['FotoUrl'] = gerar_url_foto(p.get('ParceiroUUID', ''))

            # Telefone
            telefone = p.get('Telefone', '') or ''
            if not telefone and p.get('WhatsAppID'):
                whats_id = str(p.get('WhatsAppID', ''))
                telefone = (
                    whats_id.replace('whatsapp:+55', '')
                             .replace('whatsapp:+', '')
                             .replace('whatsapp:', '')
                )
            p['TelefoneFormatado'] = formatar_telefone(telefone)

            # Documento
            if p.get('CNPJ'):
                p['DocumentoFormatado'] = formatar_documento(p.get('CNPJ'))
                p['TipoDocumento'] = 'CNPJ'
            else:
                p['DocumentoFormatado'] = formatar_documento(p.get('CPF'))
                p['TipoDocumento'] = 'CPF'

            # Status
            status_p = p.get('StatusAtual', 'ATIVO') or 'ATIVO'
            status_info = _STATUS_DESC.get(status_p, _STATUS_DESC['ATIVO'])
            p['StatusLabel'] = status_info['label']
            p['StatusColor'] = status_info['color']

            # Habilidades
            habs = [
                catalogo_desc.get(int(x), f"Serviço {x}")
                for x in p.get('HabIDs', '').split(',') if x
            ]
            p['HabilidadesDesc'] = ", ".join(habs) if habs else "Não informado"
            p['HabilidadesList'] = habs

            # Disponibilidade
            disp_list = []
            if p.get('DispRaw'):
                for item in p['DispRaw'].split('|'):
                    try:
                        dia_id, per_id = map(int, item.split(':'))
                        disp_list.append({
                            'dia': _DIAS_DESC.get(dia_id, 'N/A'),
                            'periodo': _PERIODOS_DESC.get(per_id, 'N/A'),
                            'texto': f"{_DIAS_DESC.get(dia_id, 'N/A')} ({_PERIODOS_DESC.get(per_id, 'N/A')})",
                        })
                    except Exception:
                        pass
            p['DisponibilidadeDesc'] = disp_list

        # 4. Ordenar por distância
        parceiros.sort(key=lambda p: p.get('distancia', 999.0))

        return parceiros
