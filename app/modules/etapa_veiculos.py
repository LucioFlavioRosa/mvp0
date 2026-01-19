from app.core.database import DatabaseManager

class EtapaVeiculos:
    def __init__(self):
        self.db = DatabaseManager()
        
        self.TEMPLATE_PERGUNTA_CARRO = "HX92d60698b590fe47e24e166d65531eef" 
        self.TEMPLATE_PERGUNTA_MOTO = "HX60b961f0da4b9d7b7f623e7fa0a77d67"
        self.TEMPLATE_SEMANA = "HXbe40fbb6741a733ebc2182ede584cc05"

    def iniciar_modulo(self, sender_id):
        """Chamado quando termina Habilidades ou Retoma do zero"""
        # Inicia perguntando do CARRO
        return 'AGUARDANDO_VEICULO_CARRO', {
            'tipo': 'template',
            'sid': self.TEMPLATE_PERGUNTA_CARRO,
            'variaveis': {}
        }

    # 🟢 NOVO MÉTODO: Permite retomar exatamente onde parou (Carro ou Moto)
    def reenviar_etapa_atual(self, step_atual):
        if step_atual == 'AGUARDANDO_VEICULO_CARRO':
            return step_atual, {
                'tipo': 'template',
                'sid': self.TEMPLATE_PERGUNTA_CARRO,
                'variaveis': {}
            }
        elif step_atual == 'AGUARDANDO_VEICULO_MOTO':
            return step_atual, {
                'tipo': 'template',
                'sid': self.TEMPLATE_PERGUNTA_MOTO,
                'variaveis': {}
            }
        return None

    def _salvar_veiculo_db(self, tipo_id, sender_id):
        sql = """
        INSERT INTO PARCEIROS_VEICULOS (VeiculoID, ParceiroUUID, TipoVeiculoID, Placa, Ativo)
        SELECT NEWID(), P.ParceiroUUID, ?, NULL, 1
        FROM PARCEIROS_PERFIL P
        WHERE P.WhatsAppID = ?
        AND NOT EXISTS (
            SELECT 1 FROM PARCEIROS_VEICULOS PV 
            WHERE PV.ParceiroUUID = P.ParceiroUUID 
            AND PV.TipoVeiculoID = ?
        )
        """
        self.db.execute_write(sql, (tipo_id, sender_id, tipo_id))

    def processar_carro(self, texto, sender_id):
        resp = texto.strip().upper()
        
        # Validação Sim/Não
        if resp not in ['SIM', 'S', 'NAO', 'NÃO', 'N']:
            return 'AGUARDANDO_VEICULO_CARRO', {'tipo': 'texto', 'conteudo': "⚠️ Resposta inválida. Você tem Carro? Responda SIM ou NÃO."}

        # Salva se for SIM (Carro = ID 2)
        if resp in ['SIM', 'S']:
            self._salvar_veiculo_db(2, sender_id)

        # 🟢 Avança para MOTO
        return 'AGUARDANDO_VEICULO_MOTO', {
            'tipo': 'template',
            'sid': self.TEMPLATE_PERGUNTA_MOTO,
            'variaveis': {}
        }

    def processar_moto(self, texto, sender_id):
        resp = texto.strip().upper()

        # Validação Sim/Não
        if resp not in ['SIM', 'S', 'NAO', 'NÃO', 'N']:
            return 'AGUARDANDO_VEICULO_MOTO', {'tipo': 'texto', 'conteudo': "⚠️ Resposta inválida. Você tem Moto? Responda SIM ou NÃO."}

        # Salva se for SIM (Moto = ID 1)
        if resp in ['SIM', 'S']:
            self._salvar_veiculo_db(1, sender_id)

        # 🟢 Avança para o bloco da SEMANA
        return 'AGUARDANDO_DISPONIBILIDADE_SEMANA', {
            'tipo': 'sequencia',
            'mensagens': [
                {
                    'tipo': 'texto', 
                    'conteudo': "✅ Etapa finalizada com sucesso!", 
                    'delay': 1
                },
                {
                    'tipo': 'texto', 
                    'conteudo': "🗓️ *Na próxima etapa vamos registar sua disponibilidade.*", 
                    'delay': 2
                },
                {
                    'tipo': 'texto', 
                    'conteudo': "Lembrando que você NÃO será obrigado a aceitar nenhum trabalho.", 
                    'delay': 2
                },
                {
                    'tipo': 'template',
                    'sid': self.TEMPLATE_SEMANA, 
                    'variaveis': {},
                    'delay': 2
                }
            ]
        }