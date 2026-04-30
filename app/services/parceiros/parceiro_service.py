from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload, defer
from app.models import ParceiroPerfil, ParceiroHabilidade, ParceiroVeiculo, PedidoServico, CatalogoServico
from app.core.database import DatabaseManager
from app.core.config import Settings
import uuid
import random
import time
import os
from app.schemas.enums import StatusParceiro, StatusPedido

class ParceiroService:
    def __init__(self):
        self.db = DatabaseManager()

    # =========================================================================
    # HELPERS PRIVADOS DE FORMATAÇÃO
    # =========================================================================

    @staticmethod
    def _resolver_habilidades(db_session, hab_ids_str: str) -> list:
        """Resolve os IDs de habilidades para nomes legíveis consultando o CATALOGO_SERVICOS."""
        if not hab_ids_str:
            return []
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
    # ... (manter métodos de salvar) ...
    def getWhatsappID(self, parceiro_uuid):
        sql = "SELECT WhatsAppID FROM PARCEIROS_PERFIL WHERE ParceiroUUID = ?"
        row_user = self.db.execute_read_one(sql, (parceiro_uuid,))
        if row_user:
            return row_user[0]
        else:
            return None

    def salvar_cnpj_inicial(self, whatsapp_id, cnpj_limpo):
        parceiro_uuid = str(uuid.uuid4())
        sql = """
        MERGE PARCEIROS_PERFIL AS target
        USING (SELECT ? AS WA_ID) AS source ON (target.WhatsAppID = source.WA_ID)
        WHEN MATCHED THEN
            UPDATE SET CNPJ = ?, StatusAtual = ?
        WHEN NOT MATCHED THEN
            INSERT (ParceiroUUID, WhatsAppID, CNPJ, StatusAtual)
            VALUES (?, ?, ?, ?);
        """
        status_andamento = StatusParceiro.EM_ANALISE.value # Antigo EM_ANDAMENTO
        return self.db.execute_write(sql, (whatsapp_id, cnpj_limpo, status_andamento, parceiro_uuid, whatsapp_id, cnpj_limpo, status_andamento))

    def validar_cnpj_api(self, cnpj):
        time.sleep(1) 
        if cnpj.endswith("0000"):
            return False, "CNPJ Baixado ou Inapto"
        return True, "Ativo"

    def salvar_cpf(self, whatsapp_id, cpf):
        sql = "UPDATE PARCEIROS_PERFIL SET CPF = ? WHERE WhatsAppID = ?"
        return self.db.execute_write(sql, (cpf, whatsapp_id))

    def salvar_nome(self, whatsapp_id, nome):
        sql = "UPDATE PARCEIROS_PERFIL SET NomeCompleto = ? WHERE WhatsAppID = ?"
        return self.db.execute_write(sql, (nome, whatsapp_id))

    def buscar_cidade_por_cep(self, cep):
        return "Belém", "PA" 

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
        lat = -1.455 + (random.random() * 0.001)
        long = -48.502 + (random.random() * 0.001)
        sql = """
        UPDATE PARCEIROS_PERFIL 
        SET Numero = ?, 
            Geo_Base = geography::Point(?, ?, 4326),
            StatusAtual = ? 
        WHERE WhatsAppID = ?
        """
        return self.db.execute_write(sql, (numero, lat, long, StatusParceiro.ATIVO.value, whatsapp_id))

    # =========================================================================
    # GESTÃO DE PARCEIROS (PORTAL BFF)
    # =========================================================================
    
    @staticmethod
    def listar_parceiros(db_session, filtros: dict) -> dict:
        stmt = select(ParceiroPerfil).options(
            selectinload(ParceiroPerfil.habilidades).joinedload(ParceiroHabilidade.servico_ref),
            selectinload(ParceiroPerfil.veiculos).joinedload(ParceiroVeiculo.tipo_veiculo),
            selectinload(ParceiroPerfil.pedidos_alocados).joinedload(PedidoServico.tipo_servico_ref),
            defer(ParceiroPerfil.Geo_Base)
        )

        if filtros.get("status"):
            stmt = stmt.where(ParceiroPerfil.StatusAtual == filtros["status"])
        if filtros.get("cidade"):
            stmt = stmt.where(ParceiroPerfil.Cidade == filtros["cidade"])
        if filtros.get("nome"):
            stmt = stmt.where(ParceiroPerfil.NomeCompleto.ilike(f"%{filtros['nome']}%"))

        parceiros_obj = db_session.execute(stmt).scalars().all()

        total_ativos = 0
        total_analise = 0
        cidades_set = set()
        parceiros_list = []

        for p in parceiros_obj:
            status = (p.StatusAtual or "").upper()
            if status == StatusParceiro.ATIVO.value:
                total_ativos += 1
            elif status == StatusParceiro.EM_ANALISE.value:
                total_analise += 1

            if p.Cidade:
                cidades_set.add(p.Cidade)

            uuid_str = str(p.ParceiroUUID)
            nomes_habilidades = [h.servico_ref.Nome for h in p.habilidades if h.servico_ref]
            ids_habilidades = ",".join([str(h.TipoServicoID) for h in p.habilidades])
            veiculos_str = ", ".join([v.tipo_veiculo.NomeVeiculo for v in p.veiculos if v.tipo_veiculo and v.Ativo]) or None
            total_recebidas = len(p.pedidos_alocados)
            total_concluidas = len([o for o in p.pedidos_alocados if o.StatusPedido == StatusPedido.FINALIZADO.value])
            taxa_aceite = round((total_concluidas / total_recebidas) * 100, 1) if total_recebidas > 0 else None

            parceiros_list.append({
                "ParceiroUUID": uuid_str,
                "NomeCompleto": p.NomeCompleto,
                "Cidade": p.Cidade,
                "Bairro": p.Bairro,
                "Rua": p.Rua,
                "Numero": p.Numero,
                "CEP": p.CEP,
                "Telefone": p.WhatsAppID,
                "Documento": p.CNPJ or p.CPF,
                "FotoUrl": f"{Settings().BASE_STORAGE_URL}/{uuid_str.upper()}/selfie.jpg",
                "HabilidadesList": nomes_habilidades,
                "RaioAtuacao": p.DistanciaMaximaKm,
                "StatusAtual": p.StatusAtual,
                "Veiculos": veiculos_str,
                "HabIDs": ids_habilidades,
                "TotalOrdensConcluidas": total_concluidas,
                "TaxaAceite": taxa_aceite
            })

        total_outros = len(parceiros_list) - total_ativos - total_analise
        cidades_lista = sorted(list(cidades_set))

        return {
            "parceiros": parceiros_list,
            "total_ativos": total_ativos,
            "total_analise": total_analise,
            "total_outros": total_outros,
            "cidades": cidades_lista,
            "filtros_disponiveis": {
                "lista_status": [e.value for e in StatusParceiro]
            }
        }

    @staticmethod
    def obter_detalhes_parceiro(db_session, parceiro_uuid: str) -> dict:
        stmt = select(ParceiroPerfil).options(
            selectinload(ParceiroPerfil.habilidades).joinedload(ParceiroHabilidade.servico_ref),
            selectinload(ParceiroPerfil.disponibilidades),
            selectinload(ParceiroPerfil.pedidos_alocados).joinedload(PedidoServico.tipo_servico_ref),
            defer(ParceiroPerfil.Geo_Base)
        ).where(ParceiroPerfil.ParceiroUUID == parceiro_uuid)

        parceiro = db_session.execute(stmt).scalars().first()
        if not parceiro:
            return None
            
        # Preparação de Dados (Fase 1.3)
        uuid_upper = str(parceiro.ParceiroUUID).upper()
        foto_url = f"{Settings().BASE_STORAGE_URL}/{uuid_upper}/selfie.jpg"

        parceiro_dict = {
            "ParceiroUUID": str(parceiro.ParceiroUUID),
            "NomeCompleto": parceiro.NomeCompleto, # Retorna None se não houver
            "Cidade": parceiro.Cidade,
            "Bairro": parceiro.Bairro,
            "Rua": parceiro.Rua,
            "Numero": parceiro.Numero,
            "CEP": parceiro.CEP,
            "Telefone": parceiro.WhatsAppID,
            "Email": parceiro.Email,
            "Documento": parceiro.CNPJ or parceiro.CPF,
            "StatusAtual": parceiro.StatusAtual,
            "DistanciaMaximaKm": parceiro.DistanciaMaximaKm,
            "ChavePix": parceiro.chave_pix,
            "Aceite": True,
            "FotoUrl": foto_url,
            "TotalOrdensRecebidas": len(parceiro.pedidos_alocados),
            "TotalOrdensConcluidas": len([o for o in parceiro.pedidos_alocados if o.StatusPedido == StatusPedido.FINALIZADO.value]),
            "TaxaAceite": round((len([o for o in parceiro.pedidos_alocados if o.StatusPedido == StatusPedido.FINALIZADO.value]) / len(parceiro.pedidos_alocados)) * 100, 1) if len(parceiro.pedidos_alocados) > 0 else None
        }
        
        habilidades = [h.servico_ref.Nome for h in parceiro.habilidades if h.servico_ref]
        disponibilidade = [
            {"dia_id": d.DiaSemana, "periodo_id": d.Periodo}
            for d in parceiro.disponibilidades if d.Ativo
        ]
            
        ordens_list = []
        for ped in parceiro.pedidos_alocados:
            ordens_list.append({
                "OrdemID": str(ped.PedidoID),
                "PedidoID": ped.NumeroOSSCAE or str(ped.PedidoID)[:8],
                "Atividade": ped.tipo_servico_ref.Nome if ped.tipo_servico_ref else None,
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
        stmt = select(ParceiroPerfil).options(
            selectinload(ParceiroPerfil.pedidos_alocados).joinedload(PedidoServico.tipo_servico_ref),
            defer(ParceiroPerfil.Geo_Base)
        ).order_by(ParceiroPerfil.NomeCompleto)

        parceiros_db = db_session.execute(stmt).scalars().all()
        parceiros_list = []

        for p in parceiros_db:
            uuid_str = str(p.ParceiroUUID)
            
            # Preparação de Dados (Fase 1.3)
            foto_url = f"{Settings().BASE_STORAGE_URL}/{uuid_str.upper()}/selfie.jpg"

            item_parceiro = {
                "ParceiroUUID": uuid_str,
                "NomeCompleto": p.NomeCompleto,
                "Cidade": p.Cidade,
                "Telefone": p.WhatsAppID,
                "Documento": p.CNPJ or p.CPF,
                "StatusAtual": p.StatusAtual,
                "FotoUrl": foto_url,
                "ordens": [] 
            }

            for ped in p.pedidos_alocados:
                item_parceiro["ordens"].append({
                    "PedidoID": str(ped.PedidoID),
                    "AtividadeDesc": ped.tipo_servico_ref.Nome if ped.tipo_servico_ref else None,
                    "CidadePedido": ped.Cidade,
                    "Urgencia": ped.Urgencia,
                    "DataLimite": ped.PrazoConclusaoOS,
                    "StatusOrdem": ped.StatusPedido
                })

            parceiros_list.append(item_parceiro)

        return {"parceiros_os": parceiros_list}

