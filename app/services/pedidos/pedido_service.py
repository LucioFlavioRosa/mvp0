from sqlalchemy.orm import Session, contains_eager, joinedload
from sqlalchemy import distinct, select, case
from app.models import PedidoServico, Unidade, CatalogoServico, VwParceiroDetalhado
from typing import Optional, Dict, Any, List
import uuid
from datetime import datetime
from app.schemas.pedido import ParceiroDetalheResponse, PedidoCreateRequest, PedidoUpdateRequest
from sqlalchemy import literal_column
from sqlalchemy.orm import selectinload, defer
from app.models import ParceiroPerfil, ParceiroHabilidade, ParceiroVeiculo, ParceiroDisponibilidade
from app.services.parceiros.parceiro_service import ParceiroService
from app.services.infra.geocoding_service import GeocodingService
from geopy.distance import geodesic

class PedidoService:
    @staticmethod
    def get_pedidos(
        db: Session,
        status: Optional[str] = None,
        urgencia: Optional[str] = None,
        unidade_nome: Optional[str] = None,
        tipo_servico_nome: Optional[str] = None,
        bloco: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retorna a lista de pedidos filtrados e ordena, imitando a lógica central do portal.
        Também retorna os valores únicos para os dropdowns de filtro.
        """
        # 1. Busca filtros disponíveis (Todas as opções possíveis para Unidades/Serviços, mas em uso para Status/Urgência)
        lista_status = db.execute(select(distinct(PedidoServico.StatusPedido)).where(PedidoServico.StatusPedido != None)).scalars().all()
        lista_urgencia = db.execute(select(distinct(PedidoServico.Urgencia)).where(PedidoServico.Urgencia != None)).scalars().all()

        stmt_unidades = select(distinct(Unidade.NomeUnidade)).order_by(Unidade.NomeUnidade.asc())
        lista_unidades = db.execute(stmt_unidades).scalars().all() 

        stmt_tipos_servicos = select(distinct(CatalogoServico.Nome)).order_by(CatalogoServico.Nome.asc())
        lista_tipos_servicos = db.execute(stmt_tipos_servicos).scalars().all() 

        lista_blocos = ["Bloco A", "Bloco B", "Bloco C", "Bloco D"]

        # 2. Query Principal de Pedidos
        stmt = (
            select(PedidoServico)
            .join(PedidoServico.tipo_servico_ref) 
            .join(PedidoServico.unidade_obj) 
            .options(contains_eager(PedidoServico.tipo_servico_ref))
            .options(contains_eager(PedidoServico.unidade_obj))
        )            
        
        if status:
            stmt = stmt.where(PedidoServico.StatusPedido == status)
        if urgencia:
            stmt = stmt.where(PedidoServico.Urgencia == urgencia)
        if unidade_nome:
            stmt = stmt.where(Unidade.NomeUnidade == unidade_nome)
        if tipo_servico_nome:
            stmt = stmt.where(CatalogoServico.Nome == tipo_servico_nome)
        if bloco:
            stmt = stmt.where(PedidoServico.Bloco == bloco)
        
        # Ordenação Centralizada
        stmt = stmt.order_by(
            case(
                (PedidoServico.StatusPedido == 'AGUARDANDO', 1),
                (PedidoServico.StatusPedido == 'DISPARADO', 2),
                (PedidoServico.StatusPedido == 'VINCULADO', 3),
                (PedidoServico.StatusPedido == 'FINALIZADO', 4),
                (PedidoServico.StatusPedido == 'CANCELADO', 5),
                else_=6
            ),
            case(
                (PedidoServico.Urgencia == 'MAXIMA', 1),
                (PedidoServico.Urgencia == 'URGENTE', 2),
                (PedidoServico.Urgencia.in_(['JUIZADO', 'PROCON', 'IMPRENSA']), 3),
                (PedidoServico.Urgencia.in_(['DIRETORIA', 'OUVIDORIA', 'SOCIAL']), 4),
                (PedidoServico.Urgencia == 'NORMAL', 5),
                else_=6
            ),
            PedidoServico.PrazoConclusaoOS.asc()
        )
        
        pedidos_obj = db.execute(stmt).scalars().all()
        
        # Formatando para o Response Schema
        pedidos_formatados = []
        for p in pedidos_obj:
            p_dict = p.to_dict()
            p_dict['TempoMedio'] = p.tipo_servico_ref.TempoMedioExecucao if p.tipo_servico_ref else 0.0
            p_dict['Atividade'] = p.tipo_servico_ref.Nome if p.tipo_servico_ref else "Serviço Não Encontrado"
            p_dict['UnidadeNome'] = p.unidade_obj.NomeUnidade if p.unidade_obj else None
            p_dict['PrazoConclusaoOS'] = p.PrazoConclusaoOS if p.PrazoConclusaoOS else None
            pedidos_formatados.append(p_dict)
            
        return {
            "pedidos": pedidos_formatados,
            "filtros_disponiveis": {
                "lista_status": lista_status,
                "lista_urgencias": lista_urgencia,
                "lista_unidades": lista_unidades,
                "lista_tipos_servicos": lista_tipos_servicos,
                "lista_blocos": lista_blocos
            }
        }

    @staticmethod
    def obter_pedido_detalhado(db: Session, pedido_uuid: str) -> Dict[str, Any]:
        """
        Busca um pedido específico e resolve o Match de Parceiros.
        """
        pedido = None
        parceiros_final = []
        lat_pedido, lng_pedido = -1.4558, -48.4902
        
        try:
            pid = uuid.UUID(pedido_uuid)
        except ValueError:
            return {"pedido": None, "parceiros": []}

        try:
            # Busca pedido
            stmt = select(PedidoServico).options(joinedload(PedidoServico.tipo_servico_ref)).where(PedidoServico.PedidoID == pid)
            pedido_obj = db.execute(stmt).scalars().first()
            
            if pedido_obj:
                pedido = pedido_obj.to_dict()
                
                # Adicionando o nome do serviço para exibição no template
                pedido['Atividade'] = pedido_obj.tipo_servico_ref.Nome if pedido_obj.tipo_servico_ref else "Serviço Não Informado"
                
                # Formatação de campos
                pedido['PrazoConclusaoOS'] = pedido_obj.PrazoConclusaoOS if pedido_obj.PrazoConclusaoOS else None

                status = pedido['StatusPedido'] if pedido['StatusPedido'] else 'Aguardando'
                
                stmt_parc = None
                
                # Busca padrão base para parceiros com dados geográficos
                base_stmt = (
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
                )

                parceiros_db = []
                if status.upper() == 'AGUARDANDO':
                    # Mostra todos os parceiros disponíveis (ATIVOS) para o tipo de serviço da OS
                    ts_id = int(pedido['TipoServicoID'])
                    stmt_parc = (
                        base_stmt
                        .join(ParceiroPerfil.habilidades)
                        .where(
                            ParceiroHabilidade.TipoServicoID == ts_id,
                            ParceiroPerfil.StatusAtual == 'ATIVO'
                        )
                    )
                    parceiros_db = db.execute(stmt_parc).all()

                elif status.upper() in ['VINCULADO', 'FINALIZADO', 'CANCELADO']:
                    parceiro_id = str(pedido['ParceiroAlocadoUUID'])
                    # Traz o parceiro alocado, independente do status atual dele
                    stmt_parc = base_stmt.where(ParceiroPerfil.ParceiroUUID == parceiro_id)
                    parceiros_db = db.execute(stmt_parc).all()

                parceiros_final = []
                
                for row in parceiros_db:
                    p = row[0]       # ParceiroPerfil
                    p_lat = row[1]   # Latitude do banco
                    p_lng = row[2]   # Longitude do banco
                    uuid_str = str(p.ParceiroUUID)

                    # Geocoding fallback se não tiver geo_base
                    if p_lat is None or p_lng is None:
                        try:
                            p_lat_geo, p_lng_geo = GeocodingService.geocodificar_endereco(
                                rua=p.Rua, numero=str(p.Numero) if p.Numero else "S/N", bairro=p.Bairro, cidade=p.Cidade
                            )
                            if p_lat_geo is not None:
                                p_lat, p_lng = p_lat_geo, p_lng_geo
                        except Exception:
                            pass
                    
                    # Distancia
                    distancia = None
                    if p_lat is not None and p_lng is not None and pedido.get('Lat') and pedido.get('Lng'):
                        try:
                            distancia = round(geodesic((p_lat, p_lng), (float(pedido['Lat']), float(pedido['Lng']))).kilometers, 2)
                        except Exception:
                            pass

                    # Formatações via ParceiroService
                    tipo_doc, doc_formatado = ParceiroService._formatar_documento(p.CPF, p.CNPJ)
                    nomes_hab = [h.servico_ref.Nome for h in p.habilidades if h.servico_ref]
                    veiculos_str = ", ".join([v.tipo_veiculo.NomeVeiculo for v in p.veiculos if v.tipo_veiculo and v.Ativo]) or "Nenhum"
                    
                    disp_list = []
                    for d in p.disponibilidades:
                        if d.Ativo:
                            disp_list.append({
                                "dia_id": d.DiaSemana,
                                "periodo_id": d.Periodo
                            })

                    total_recebidas = len(p.pedidos_alocados)
                    total_concluidas = len([o for o in p.pedidos_alocados if o.StatusPedido == 'CONCLUIDO'])
                    
                    parceiros_final.append({
                        "ParceiroUUID": uuid_str,
                        "NomeCompleto": p.NomeCompleto,
                        "Cidade": p.Cidade,
                        "Bairro": p.Bairro,
                        "Rua": p.Rua,
                        "Numero": str(p.Numero) if p.Numero else 'S/N',
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
                        "RaioAtuacao": p.DistanciaMaximaKm or 0,
                        "TotalOrdensConcluidas": total_concluidas,
                        "TotalOrdensRecebidas": total_recebidas,
                        "AvaliacaoMediaFormatada": None,
                        "DisponibilidadeList": disp_list,
                        "UltimoAtendimentoDataFormatado": None
                    })

                # Ordena por distância
                parceiros_final = sorted(parceiros_final, key=lambda x: x['distancia'] if x['distancia'] is not None else 9999)

        except Exception as e:
            print(f"🔥 [BACKEND] Erro ao buscar detalhes do pedido: {e}")
            import traceback
            traceback.print_exc()

        return {
            "pedido": pedido,
            "parceiros": parceiros_final
        }

    @staticmethod
    def desvincular_parceiro(db: Session, pedido_uuid: str, mensagem: str = None) -> bool:
        """
        Remove o parceiro alocado de um pedido e volta seu status para AGUARDANDO.
        """
        try:
            pid = uuid.UUID(pedido_uuid)
            pedido = db.query(PedidoServico).filter(PedidoServico.PedidoID == pid).first()
            
            if not pedido:
                return False

            # Lógica legada: Limpar vínculo e resetar status
            pedido.ParceiroAlocadoUUID = None
            pedido.StatusPedido = 'AGUARDANDO'
            
            if mensagem:
                # Adiciona a justificativa à observação mantendo o que já existia
                obs_atual = pedido.Observacao or ""
                pedido.Observacao = f"{obs_atual}\n[DESVINCULAR]: {mensagem}".strip() # Corrigir para envio de mensagem

            db.commit()
            return True
        except Exception as e:
            db.rollback()
            print(f"🔥 Erro ao desvincular pedido {pedido_uuid}: {e}")
            return False
            
    @staticmethod
    def criar_pedido(db: Session, dados: PedidoCreateRequest) -> Optional[PedidoServico]:
        """
        Cria uma nova Ordem de Serviço no banco de dados via ORM.
        Aplica geocodificação automática caso não venha no payload.
        """
        from app.services.infra.geocoding_service import GeocodingService
        
        try:
            lat = dados.Lat
            lng = dados.Lng
            
            if lat is None or lng is None:
                lat, lng = GeocodingService.geocodificar_endereco(
                    rua=dados.Rua, 
                    numero=dados.Numero, 
                    bairro=dados.Bairro, 
                    cidade=dados.Cidade
                )
                dados.Lat = lat
                dados.Lng = lng

            novo_pedido = PedidoServico(**dados.dict())
            db.add(novo_pedido)
            db.commit()
            db.refresh(novo_pedido)
            return novo_pedido
        except Exception as e:
            db.rollback()
            print(f"🔥 Erro ao criar pedido: {e}")
            return None

    @staticmethod
    def atualizar_pedido(db: Session, pedido_uuid: str, dados: PedidoUpdateRequest) -> Optional[PedidoServico]:
        """
        Atualiza campos de um pedido existente (PATCH).
        """
        try:
            pid = uuid.UUID(pedido_uuid)
            pedido = db.query(PedidoServico).filter(PedidoServico.PedidoID == pid).first()
            
            if not pedido:
                return None

            update_data = dados.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(pedido, key, value)

            db.commit()
            db.refresh(pedido)
            return pedido
        except Exception as e:
            db.rollback()
            print(f"🔥 Erro ao atualizar pedido {pedido_uuid}: {e}")
            return None
