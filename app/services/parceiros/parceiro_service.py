from app.core.database import DatabaseManager
import uuid
import random
import time

class ParceiroService:
    def __init__(self):
        self.db = DatabaseManager()

    # =========================================================================
    # HELPERS PRIVADOS DE FORMATAÇÃO
    # =========================================================================

    @staticmethod
    def _formatar_telefone(telefone: str) -> str:
        import re
        if not telefone:
            return "Não informado"
        nums = re.sub(r'\D', '', str(telefone))
        if len(nums) == 11:
            return f"({nums[:2]}) {nums[2:7]}-{nums[7:]}"
        elif len(nums) == 10:
            return f"({nums[:2]}) {nums[2:6]}-{nums[6:]}"
        return telefone

    @staticmethod
    def _formatar_documento(cpf: str, cnpj: str):
        import re
        doc = cnpj or cpf
        tipo = "CNPJ" if cnpj else ("CPF" if cpf else "N/I")
        if not doc:
            return tipo, "Não informado"
        nums = re.sub(r'\D', '', str(doc))
        if len(nums) == 14:
            return tipo, f"{nums[:2]}.{nums[2:5]}.{nums[5:8]}/{nums[8:12]}-{nums[12:]}"
        elif len(nums) == 11:
            return tipo, f"{nums[:3]}.{nums[3:6]}.{nums[6:9]}-{nums[9:]}"
        return tipo, doc

    @staticmethod
    def _formatar_status(status: str) -> str:
        mapa = {
            "ATIVO": "Ativo",
            "EM_ANALISE": "Em Análise",
            "SUSPENSO": "Suspenso",
            "INATIVO": "Inativo",
        }
        if not status:
            return "Desconhecido"
        return mapa.get(status.upper(), status.replace("_", " ").title())

    @staticmethod
    def _resolver_habilidades(db_session, hab_ids_str: str) -> list:
        """Resolve os IDs de habilidades para nomes legíveis consultando o CATALOGO_SERVICOS."""
        if not hab_ids_str:
            return []
        from sqlalchemy import select
        from app.models import CatalogoServico
        ids = []
        for x in hab_ids_str.split(','):
            try:
                ids.append(int(x.strip()))
            except ValueError:
                pass
        if not ids:
            return []
        servicos = db_session.execute(
            select(CatalogoServico.ServicoID, CatalogoServico.Nome)
            .where(CatalogoServico.ServicoID.in_(ids))
        ).all()
        mapa = {s.ServicoID: s.Nome for s in servicos}
        return [mapa.get(i, f"Serviço {i}") for i in ids]

    # --- DADOS PESSOAIS ---

    def getWhatsappID(self, parceiro_uuid):
        sql = "SELECT WhatsAppID FROM PARCEIROS_PERFIL WHERE ParceiroUUID = ?"
        row_user = self.db.execute_read_one(sql, (parceiro_uuid,))
        if row_user:
            return row_user[0]
        else:
            return None

    def salvar_cnpj_inicial(self, whatsapp_id, cnpj_limpo):
        """
        Primeiro passo de dados: Cria ou Atualiza o registro inicial.
        Gera o UUID do parceiro aqui.
        """
        parceiro_uuid = str(uuid.uuid4())
        
        # MERGE: Se já existe (pelo WhatsAppID), atualiza CNPJ. Se não, cria.
        sql = """
        MERGE PARCEIROS_PERFIL AS target
        USING (SELECT ? AS WA_ID) AS source ON (target.WhatsAppID = source.WA_ID)
        WHEN MATCHED THEN
            UPDATE SET CNPJ = ?, StatusAtual = 'EM_ANDAMENTO'
        WHEN NOT MATCHED THEN
            INSERT (ParceiroUUID, WhatsAppID, CNPJ, StatusAtual)
            VALUES (?, ?, ?, 'EM_ANDAMENTO');
        """
        return self.db.execute_write(sql, (whatsapp_id, cnpj_limpo, parceiro_uuid, whatsapp_id, cnpj_limpo))

    def validar_cnpj_api(self, cnpj):
        """
        Simula a chamada de API externa (Receita Federal/Serpro).
        Retorna: (Sucesso: Bool, Dados: Dict)
        """
        # Simulação de delay de processamento (conforme diagrama)
        time.sleep(1) 
        
        # Lógica Fake: Se terminar em 0000 é inválido, senão válido
        if cnpj.endswith("0000"):
            return False, "CNPJ Baixado ou Inapto"
        return True, "Ativo"

    def salvar_cpf(self, whatsapp_id, cpf):
        sql = "UPDATE PARCEIROS_PERFIL SET CPF = ? WHERE WhatsAppID = ?"
        return self.db.execute_write(sql, (cpf, whatsapp_id))

    def salvar_nome(self, whatsapp_id, nome):
        sql = "UPDATE PARCEIROS_PERFIL SET NomeCompleto = ? WHERE WhatsAppID = ?"
        return self.db.execute_write(sql, (nome, whatsapp_id))

    # --- ENDEREÇO ---

    def buscar_cidade_por_cep(self, cep):
        """
        Simula API ViaCEP.
        """
        # Em produção: requests.get(f"https://viacep.com.br/ws/{cep}/json/")
        return "Belém", "PA" # Mock fixo para o projeto

    def salvar_cep_cidade(self, whatsapp_id, cep, cidade):
        sql = "UPDATE PARCEIROS_PERFIL SET CEP = ?, Cidade = ? WHERE WhatsAppID = ?"
        return self.db.execute_write(sql, (cep, cidade, whatsapp_id))

    def salvar_rua(self, whatsapp_id, rua):
        sql = "UPDATE PARCEIROS_PERFIL SET Rua = ? WHERE WhatsAppID = ?"
        return self.db.execute_write(sql, (rua, whatsapp_id))

    def salvar_bairro(self, whatsapp_id, bairro):
        sql = "UPDATE PARCEIROS_PERFIL SET Bairro = ? WHERE WhatsAppID = ?"
        return self.db.execute_write(sql, (bairro, whatsapp_id))

    def finalizar_endereco_com_geo(self, whatsapp_id, numero):
        """
        Salva o número, calcula a Geolocation e atualiza o status.
        """
        # 1. Simula cálculo de Lat/Long (Google Maps API)
        lat = -1.455 + (random.random() * 0.001)
        long = -48.502 + (random.random() * 0.001)

        # 2. Query com Geography Point do SQL Server
        sql = """
        UPDATE PARCEIROS_PERFIL 
        SET Numero = ?, 
            Geo_Base = geography::Point(?, ?, 4326),
            StatusAtual = 'ATIVO' -- Fim do bloco endereço
        WHERE WhatsAppID = ?
        """
        return self.db.execute_write(sql, (numero, lat, long, whatsapp_id))

    # =========================================================================
    # GESTÃO DE PARCEIROS (PORTAL BFF)
    # =========================================================================
    
    @staticmethod
    def listar_parceiros(db_session, filtros: dict) -> dict:
        from sqlalchemy import select
        from app.models import VwParceiroDetalhado
        
        query = select(VwParceiroDetalhado)
        
        if filtros.get("status"):
            query = query.where(VwParceiroDetalhado.StatusAtual == filtros["status"])
        if filtros.get("cidade"):
            query = query.where(VwParceiroDetalhado.Cidade == filtros["cidade"])
        if filtros.get("nome"):
            query = query.where(VwParceiroDetalhado.NomeCompleto.ilike(f"%{filtros['nome']}%"))
            
        parceiros_obj = db_session.execute(query).scalars().all()
        
        total_ativos = 0
        total_analise = 0
        
        cidades_set = set()
        parceiros_list = []
        
        for p in parceiros_obj:
            status = p.StatusAtual or ""
            if status.upper() == "ATIVO":
                total_ativos += 1
            elif status.upper() == "EM_ANALISE":
                total_analise += 1

            if p.Cidade:
                cidades_set.add(p.Cidade)

            tipo_doc, doc_formatado = ParceiroService._formatar_documento(p.CPF, p.CNPJ)

            parceiros_list.append({
                "ParceiroUUID": str(p.ParceiroUUID),
                "NomeCompleto": p.NomeCompleto,
                "Cidade": p.Cidade,
                "Bairro": p.Bairro,
                "FotoUrl": f"https://staegeadocscaddevusc.blob.core.windows.net/selfie/{str(p.ParceiroUUID).upper().strip()}/selfie.jpg",
                "TelefoneFormatado": ParceiroService._formatar_telefone(p.Telefone),
                "TipoDocumento": tipo_doc,
                "DocumentoFormatado": doc_formatado,
                "HabilidadesList": ParceiroService._resolver_habilidades(db_session, p.HabIDs),
                "RaioAtuacao": p.DistanciaMaximaKm or 0,
                "StatusAtual": p.StatusAtual,
                "StatusLabel": ParceiroService._formatar_status(p.StatusAtual),
                "Veiculos": p.Veiculos,
                "HabIDs": p.HabIDs,
                "TotalOrdensConcluidas": p.TotalOrdensConcluidas,
                "AvaliacaoMedia": p.AvaliacaoMedia
            })
            
        total_outros = len(parceiros_list) - total_ativos - total_analise
        cidades_lista = sorted(list(cidades_set))
        
        return {
            "parceiros": parceiros_list,
            "total_ativos": total_ativos,
            "total_analise": total_analise,
            "total_outros": total_outros,
            "cidades": cidades_lista
        }

    @staticmethod
    def obter_detalhes_parceiro(db_session, parceiro_uuid: str) -> dict:
        """
        Retorna detalhes completos de um parceiro (perfil, habilidades, disponibilidade e ordens).
        Usa relacionamentos do SQLAlchemy para carregar tudo em uma única query estruturada.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload, joinedload, defer
        from app.models import ParceiroPerfil, PedidoServico, ParceiroHabilidade

        # 1. Busca perfil, habilidades, disponibilidade e pedidos em uma única query otimizada
        stmt = select(ParceiroPerfil).options(
            selectinload(ParceiroPerfil.habilidades).joinedload(ParceiroHabilidade.servico_ref),
            selectinload(ParceiroPerfil.disponibilidades),
            selectinload(ParceiroPerfil.pedidos_alocados).joinedload(PedidoServico.tipo_servico_ref),
            defer(ParceiroPerfil.Geo_Base)
        ).where(ParceiroPerfil.ParceiroUUID == parceiro_uuid)

        parceiro = db_session.execute(stmt).scalars().first()
        
        if not parceiro:
            return None
            
        # 2. Formatação do Perfil Principal
        tipo_doc, doc_formatado = ParceiroService._formatar_documento(parceiro.CPF, parceiro.CNPJ)
        endereco = f"{parceiro.Rua or ''}, {parceiro.Numero or 'S/N'} - {parceiro.Bairro or ''}, {parceiro.Cidade or ''} - {parceiro.CEP or ''}".strip(", -")

        parceiro_dict = {
            "ParceiroUUID": str(parceiro.ParceiroUUID),
            "NomeCompleto": parceiro.NomeCompleto or "Não Informado",
            "Cidade": parceiro.Cidade,
            "TelefoneFormatado": ParceiroService._formatar_telefone(parceiro.WhatsAppID),
            "Email": parceiro.Email,
            "TipoDocumento": tipo_doc,
            "DocumentoFormatado": doc_formatado,
            "StatusAtual": parceiro.StatusAtual or "EM_ANALISE",
            "StatusLabel": ParceiroService._formatar_status(parceiro.StatusAtual or "EM_ANALISE"),
            "EnderecoCompleto": endereco,
            "DistanciaMaximaKm": parceiro.DistanciaMaximaKm,
            "ChavePix": "Cadastrada" if parceiro.StatusAtual == 'ATIVO' else "Não informada",
            "Aceite": True,
            "FotoUrl": f"https://staegeadocscaddevusc.blob.core.windows.net/selfie/{str(parceiro.ParceiroUUID).upper()}/selfie.jpg"
        }
        
        # 3. Habilidades (Processadas em memória a partir do relacionamento carregado)
        habilidades = [h.servico_ref.Nome for h in parceiro.habilidades if h.servico_ref]
        
        # 4. Disponibilidade (Processada em memória)
        dias_map = {1: 'Seg', 2: 'Ter', 3: 'Qua', 4: 'Qui', 5: 'Sex', 6: 'Sáb', 7: 'Dom'}
        periodo_map = {1: 'Manhã', 2: 'Tarde', 3: 'Noite', 4: 'Integral'}
        disponibilidade = [
            f"{dias_map.get(d.DiaSemana, 'Dia')} - {periodo_map.get(d.Periodo, 'Qualquer')}" 
            for d in parceiro.disponibilidades if d.Ativo
        ]
            
        # 5. Ordens Vinculadas (Processadas em memória)
        ordens_list = []
        for ped in parceiro.pedidos_alocados:
            ordens_list.append({
                "OrdemID": str(ped.PedidoID),
                "PedidoID": ped.NumeroOSSCAE or str(ped.PedidoID)[:8],
                "Atividade": ped.tipo_servico_ref.Nome if ped.tipo_servico_ref else "N/I",
                "CidadePedido": ped.Cidade,
                "Urgencia": ped.Urgencia,
                "StatusOrdem": ped.StatusPedido
            })
            
        return {
            "parceiro": parceiro_dict,
            "habilidades": habilidades,
            "disponibilidade": disponibilidade,
            "ordens": ordens_list
        }


    @staticmethod
    def parceiros_com_os(db_session) -> dict:
        """
        Retorna lista de parceiros e suas ordens vinculadas usando relacionamentos ORM.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload, joinedload, defer
        from app.models import ParceiroPerfil, PedidoServico

        # 1. Busca todos os parceiros carregando ordens e nomes de serviço em apenas 2 queries
        stmt = select(ParceiroPerfil).options(
            selectinload(ParceiroPerfil.pedidos_alocados).joinedload(PedidoServico.tipo_servico_ref),
            defer(ParceiroPerfil.Geo_Base)
        ).order_by(ParceiroPerfil.NomeCompleto)

        parceiros_db = db_session.execute(stmt).scalars().all()
        
        parceiros_list = []

        # 2. Monta a estrutura aninhada esperada pelo Frontend
        for p in parceiros_db:
            tipo_doc, doc_formatado = ParceiroService._formatar_documento(p.CPF, p.CNPJ)
            uuid_str = str(p.ParceiroUUID)
            
            item_parceiro = {
                "ParceiroUUID": uuid_str,
                "NomeCompleto": p.NomeCompleto,
                "Cidade": p.Cidade,
                "TelefoneFormatado": ParceiroService._formatar_telefone(p.WhatsAppID),
                "TipoDocumento": tipo_doc,
                "DocumentoFormatado": doc_formatado,
                "StatusAtual": p.StatusAtual,
                "StatusLabel": ParceiroService._formatar_status(p.StatusAtual),
                "FotoUrl": f"https://staegeadocscaddevusc.blob.core.windows.net/selfie/{uuid_str.upper()}/selfie.jpg",
                "ordens": [] # Lista vazia que será preenchida com as ordens do parceiro (Caso tenha)
            }

            # Preenche a lista de ordens (os dados já estão na memória via selectinload)
            for ped in p.pedidos_alocados:
                item_parceiro["ordens"].append({
                    "PedidoID": str(ped.PedidoID),
                    "AtividadeDesc": ped.tipo_servico_ref.Nome if ped.tipo_servico_ref else "N/I",
                    "CidadePedido": ped.Cidade,
                    "Urgencia": ped.Urgencia,
                    "DataLimiteFormatada": ped.PrazoConclusaoOS.strftime("%d/%m/%Y") if ped.PrazoConclusaoOS else None,
                    "StatusOrdem": ped.StatusPedido
                })

            parceiros_list.append(item_parceiro)

        return {"parceiros_os": parceiros_list}

