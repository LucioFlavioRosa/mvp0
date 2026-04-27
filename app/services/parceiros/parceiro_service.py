from app.core.database import DatabaseManager
import uuid
import random
import time

class ParceiroService:
    def __init__(self):
        self.db = DatabaseManager()

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
                
            parceiros_list.append({
                "ParceiroUUID": str(p.ParceiroUUID),
                "NomeCompleto": p.NomeCompleto,
                "Cidade": p.Cidade,
                "Telefone": p.Telefone,
                "StatusAtual": p.StatusAtual,
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
        from sqlalchemy import select
        from app.models import VwParceiroDetalhado, ParceiroHabilidade, ParceiroDisponibilidade, PedidoServico, CatalogoServico
        
        # 1. Perfil Principal
        parceiro = db_session.execute(
            select(VwParceiroDetalhado).where(VwParceiroDetalhado.ParceiroUUID == parceiro_uuid)
        ).scalars().first()
        
        if not parceiro:
            return None
            
        # Formata o parceiro
        def format_doc(p):
            if p.CNPJ: return "CNPJ", p.CNPJ
            if p.CPF: return "CPF", p.CPF
            return "Doc", "Não informado"
            
        tipo_doc, num_doc = format_doc(parceiro)
        
        endereco = f"{parceiro.Rua or ''}, {parceiro.NumeroEndereco or 'S/N'} - {parceiro.Bairro or ''}, {parceiro.Cidade or ''} - {parceiro.CEP or ''}".strip(", -")
        
        parceiro_dict = {
            "ParceiroUUID": str(parceiro.ParceiroUUID),
            "NomeCompleto": parceiro.NomeCompleto or "Não Informado",
            "Cidade": parceiro.Cidade,
            "TelefoneFormatado": parceiro.Telefone or "Não Informado",
            "Email": parceiro.Email,
            "TipoDocumento": tipo_doc,
            "DocumentoFormatado": num_doc,
            "StatusAtual": parceiro.StatusAtual or "EM_ANALISE",
            "StatusLabel": (parceiro.StatusAtual or "EM_ANALISE").replace("_", " ").title(),
            "EnderecoCompleto": endereco,
            "DistanciaMaximaKm": parceiro.DistanciaMaximaKm,
            "ChavePix": "Cadastrada" if parceiro.StatusAtual == 'ATIVO' else "Não informada",
            "Aceite": True, # Mockado por enquanto
            "FotoUrl": None
        }
        
        # 2. Habilidades
        # Na View VwParceiroDetalhado as habilidades estão em HabIDs, mas vamos pegar legível
        stmt_hab = select(CatalogoServico.Nome).join(ParceiroHabilidade, ParceiroHabilidade.TipoServicoID == CatalogoServico.ServicoID).where(ParceiroHabilidade.ParceiroUUID == parceiro_uuid)
        habilidades = db_session.execute(stmt_hab).scalars().all()
        
        # 3. Disponibilidade
        # Convertendo DiaSemana 1..7 para nomes (seg a dom) e periodos
        stmt_disp = select(ParceiroDisponibilidade.DiaSemana, ParceiroDisponibilidade.Periodo).where(ParceiroDisponibilidade.ParceiroUUID == parceiro_uuid).where(ParceiroDisponibilidade.Ativo == True)
        disps = db_session.execute(stmt_disp).all()
        
        dias_map = {1: 'Seg', 2: 'Ter', 3: 'Qua', 4: 'Qui', 5: 'Sex', 6: 'Sáb', 7: 'Dom'}
        periodo_map = {1: 'Manhã', 2: 'Tarde', 3: 'Noite', 4: 'Integral'}
        disponibilidade = [f"{dias_map.get(d.DiaSemana, 'Dia')} - {periodo_map.get(d.Periodo, 'Qualquer')}" for d in disps]
        if not disponibilidade:
            # Fallback se não tiver na tabela
            disponibilidade = parceiro.DispRaw.split(",") if parceiro.DispRaw else []
            
        # 4. Ordens (Pedidos vinculados)
        stmt_ordens = select(PedidoServico, CatalogoServico.Nome).join(CatalogoServico, PedidoServico.TipoServicoID == CatalogoServico.ServicoID).where(PedidoServico.ParceiroAlocadoUUID == parceiro_uuid).order_by(PedidoServico.DataCriacao.desc())
        ordens_raw = db_session.execute(stmt_ordens).all()
        
        ordens_list = []
        for ped, servico_nome in ordens_raw:
            ordens_list.append({
                "OrdemID": str(ped.PedidoID),
                "PedidoID": ped.NumeroOSSCAE or str(ped.PedidoID)[:8],
                "Atividade": servico_nome,
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
    def parceiros_com_os(db_session, filtro: str = None) -> dict:
        from sqlalchemy import select, func
        from app.models import VwParceiroDetalhado
        
        # 1. Total todos os parceiros na View
        total_todos = db_session.execute(select(func.count()).select_from(VwParceiroDetalhado)).scalar() or 0
        
        # 2. Total com OS e sem OS
        # Como a VwParceiroDetalhado tem 'TotalOrdensRecebidas'
        total_com_os = db_session.execute(select(func.count()).select_from(VwParceiroDetalhado).where(VwParceiroDetalhado.TotalOrdensRecebidas > 0)).scalar() or 0
        total_sem_os = total_todos - total_com_os
        
        # 3. Lista de parceiros
        query = select(VwParceiroDetalhado)
        if filtro == 'com_os':
            query = query.where(VwParceiroDetalhado.TotalOrdensRecebidas > 0)
        elif filtro == 'sem_os':
            query = query.where((VwParceiroDetalhado.TotalOrdensRecebidas == 0) | (VwParceiroDetalhado.TotalOrdensRecebidas == None))
            
        # Order by TotalOrdensRecebidas desc
        query = query.order_by(VwParceiroDetalhado.TotalOrdensRecebidas.desc())
        
        parceiros_obj = db_session.execute(query).scalars().all()
        
        parceiros_list = []
        for p in parceiros_obj:
            parceiros_list.append({
                "ParceiroUUID": str(p.ParceiroUUID),
                "NomeCompleto": p.NomeCompleto,
                "Cidade": p.Cidade,
                "Telefone": p.Telefone,
                "StatusAtual": p.StatusAtual,
                "TotalOrdensConcluidas": p.TotalOrdensConcluidas,
                "AvaliacaoMedia": p.AvaliacaoMedia,
                "OrdensUltimoMes": p.OrdensUltimoMes,
                "TotalOrdensRecebidas": p.TotalOrdensRecebidas,
                "UltimoAtendimentoData": p.UltimoAtendimentoData.isoformat() if p.UltimoAtendimentoData else None,
                "UltimoAtendimentoTipo": p.UltimoAtendimentoTipo
            })
            
        return {
            "parceiros_os": parceiros_list,
            "total_todos": total_todos,
            "total_com_os": total_com_os,
            "total_sem_os": total_sem_os
        }
