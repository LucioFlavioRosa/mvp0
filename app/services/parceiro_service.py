from app.core.database import DatabaseManager
import uuid
import random
import time

class ParceiroService:
    def __init__(self):
        self.db = DatabaseManager()

    # --- DADOS PESSOAIS ---

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