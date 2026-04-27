from sqlalchemy.orm import Session, contains_eager, joinedload
from sqlalchemy import distinct, select, case
from app.models import PedidoServico, Unidade, CatalogoServico, VwParceiroDetalhado
from typing import Optional, Dict, Any, List
import uuid
from datetime import datetime
from app.schemas.pedido import ParceiroDetalheResponse, PedidoCreateRequest, PedidoUpdateRequest

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
            p_dict['PrazoConclusaoOS'] = p.PrazoConclusaoOS.strftime('%d/%m/%Y %H:%M') if p.PrazoConclusaoOS else ""
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
        Busca um pedido específico e resolve o Match de Parceiros usando a lógica legada comprovada.
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
                
                # Atualizando dados espaciais
                if pedido.get('Lat') and pedido.get('Lng'):
                    lat_pedido = float(pedido['Lat'])
                    lng_pedido = float(pedido['Lng'])
                
                # Adicionando o nome do serviço para exibição no template
                pedido['Atividade'] = pedido_obj.tipo_servico_ref.Nome if pedido_obj.tipo_servico_ref else "Serviço Não Informado"
                
                # Formatação de campos
                pedido['PrazoConclusaoOS'] = pedido_obj.PrazoConclusaoOS.strftime('%d/%m/%Y-%H:%M') if pedido_obj.PrazoConclusaoOS else ""

                status = pedido['StatusPedido'] if pedido['StatusPedido'] else 'Aguardando'
                
                stmt_parc = None
                if status.upper() == 'AGUARDANDO':
                    # Ainda não selecionou um parceiro, então mostra todos os parceiros disponíveis para o tipo de serviço
                    ts_id_str = str(pedido['TipoServicoID'])
                    stmt_parc = (
                        select(VwParceiroDetalhado)
                        .where(VwParceiroDetalhado.HabIDs.contains(ts_id_str))
                    )

                elif status.upper() in ['VINCULADO', 'FINALIZADO', 'CANCELADO']:
                    parceiro_id = str(pedido['ParceiroAlocadoUUID'])
                    # Lógica para pedidos que já têm parceiro alocado
                    stmt_parc = select(VwParceiroDetalhado).where(VwParceiroDetalhado.ParceiroUUID == parceiro_id)

                if stmt_parc is not None:
                    parceiros_obj = db.execute(stmt_parc).scalars().all()
                    parceiros = [p.to_dict() for p in parceiros_obj]
                    
                    # Carregar bibliotecas e utilitários necessários para formatação
                    from geopy.distance import geodesic
                    # Vamos importar as funções utilitárias que replicam a lógica antiga do utils
                    from app.schemas.pedido import formatar_telefone, formatar_documento, gerar_url_foto
                    
                    # Dicionários mockados equivalentes aos do utils para manter a interface igual
                    STATUS_DESC = {
                        'ATIVO': {'label': 'Ativo', 'color': 'success'},
                        'INATIVO': {'label': 'Inativo', 'color': 'danger'},
                        'EM_ANALISE': {'label': 'Em Análise', 'color': 'warning'},
                        'SUSPENSO': {'label': 'Suspenso', 'color': 'danger'}
                    }
                    DIAS_DESC = {0:'Seg', 1:'Ter', 2:'Qua', 3:'Qui', 4:'Sex', 5:'Sáb', 6:'Dom'}
                    PERIODOS_DESC = {1:'Manhã', 2:'Tarde', 3:'Noite'}
                    
                    # Busca habilidades para tradução do Catalogo
                    catalogo_stmt = select(CatalogoServico.ServicoID, CatalogoServico.Nome)
                    cat_result = db.execute(catalogo_stmt).all()
                    catalogo_desc = {r.ServicoID: r.Nome for r in cat_result}

                    for p in parceiros:                    
                        # Calcula distância
                        if p.get('Lat') and p.get('Lon'):
                            try:
                                p['distancia'] = round(geodesic(
                                    (float(p['Lat']), float(p['Lon'])),
                                    (lat_pedido, lng_pedido)
                                ).kilometers, 2)
                            except:
                                p['distancia'] = 999.0
                        else:
                            p['distancia'] = 999.0
                        
                        # URL da foto
                        p['FotoUrl'] = gerar_url_foto(p.get('ParceiroUUID', ''))
                        
                        # Formata telefone
                        telefone = p.get('Telefone', '') or ''
                        if not telefone and p.get('WhatsAppID'):
                            whats_id = str(p.get('WhatsAppID', ''))
                            telefone = whats_id.replace('whatsapp:+55', '').replace('whatsapp:+', '').replace('whatsapp:', '')
                        p['TelefoneFormatado'] = formatar_telefone(telefone)
                        
                        # Formata documento
                        if p.get('CNPJ'):
                            p['DocumentoFormatado'] = formatar_documento(p.get('CNPJ'))
                            p['TipoDocumento'] = 'CNPJ'
                        else:
                            p['DocumentoFormatado'] = formatar_documento(p.get('CPF'))
                            p['TipoDocumento'] = 'CPF'
                        
                        # Status formatado
                        status_p = p.get('StatusAtual', 'ATIVO') or 'ATIVO'
                        status_info = STATUS_DESC.get(status_p, STATUS_DESC['ATIVO'])
                        p['StatusLabel'] = status_info['label']
                        p['StatusColor'] = status_info['color']
                        
                        # Habilidades
                        habs = [catalogo_desc.get(int(x), f"Serviço {x}") for x in p.get('HabIDs', '').split(',') if x]
                        p['HabilidadesDesc'] = ", ".join(habs) if habs else "Não informado"
                        p['HabilidadesList'] = habs if habs else []
                        
                        # Disponibilidade
                        disp_list = []
                        if p.get('DispRaw'):
                            for item in p['DispRaw'].split('|'):
                                try:
                                    dia_id, per_id = map(int, item.split(':'))
                                    disp_list.append({
                                        'dia': DIAS_DESC.get(dia_id, 'N/A'),
                                        'periodo': PERIODOS_DESC.get(per_id, 'N/A'),
                                        'texto': f"{DIAS_DESC.get(dia_id, 'N/A')} ({PERIODOS_DESC.get(per_id, 'N/A')})"
                                    })
                                except:
                                    pass
                        p['DisponibilidadeDesc'] = " | ".join([d['texto'] for d in disp_list]) if disp_list else "Não informado"
                        p['DisponibilidadeList'] = disp_list
                        
                        # Último atendimento formatado
                        if p.get('UltimoAtendimentoData'):
                            try:
                                p['UltimoAtendimentoDataFormatado'] = p['UltimoAtendimentoData'].strftime('%d/%m/%Y %H:%M')
                            except:
                                p['UltimoAtendimentoDataFormatado'] = "N/A"
                        else:
                            p['UltimoAtendimentoDataFormatado'] = None
                        
                        # Taxa de aceite
                        total_recebidas = p.get('TotalOrdensRecebidas', 0) or 0
                        total_concluidas = p.get('TotalOrdensConcluidas', 0) or 0
                        if total_recebidas > 0:
                            p['TaxaAceite'] = round((total_concluidas / total_recebidas) * 100, 1)
                        else:
                            p['TaxaAceite'] = None
                        
                        # Avaliação média
                        if p.get('AvaliacaoMedia'):
                            p['AvaliacaoMediaFormatada'] = round(float(p['AvaliacaoMedia']), 1)
                        else:
                            p['AvaliacaoMediaFormatada'] = None
                        
                        # Raio de atuação
                        p['RaioAtuacao'] = p.get('DistanciaMaximaKm', 0) or 0
                        
                        # Endereço completo
                        endereco_parts = [p.get('Rua', '')]
                        if p.get('NumeroEndereco'):
                            endereco_parts.append(str(p['NumeroEndereco']))
                        p['EnderecoCompleto'] = ', '.join(filter(None, endereco_parts))
                        
                        parceiros_final.append(p)
                    
                    # Ordena por distância
                    parceiros_final = sorted(parceiros_final, key=lambda x: x['distancia'])

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
                pedido.Observacao = f"{obs_atual}\n[DESVINCULAR]: {mensagem}".strip()

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

            novo_pedido = PedidoServico(
                PedidoID=uuid.uuid4(),
                StatusPedido='AGUARDANDO',
                DataCriacao=datetime.now(),
                **dados.dict()
            )
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
