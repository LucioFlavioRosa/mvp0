from app.core.database import DatabaseManager
import threading 

class EtapaHabilidades:
    def __init__(self):
        self.db = DatabaseManager()
        
        # ID do Template de Veículos (Transição)
        self.TEMPLATE_VEICULOS = "HX92d60698b590fe47e24e166d65531eef"

        # CONFIGURAÇÃO DO FLUXO
        self.FLUXO = {
            '1': {
                'id_habilidade': 1, 
                'descricao': "Manutenção de Hidrômetros", 
                'template_sid': 'HX24e1bcb7e514d6fca272f38691c76a33', 
                'proximo': 'AGUARDANDO_HABILIDADE_2'
            },
            '2': {
                'id_habilidade': 2, 
                'descricao': "Ligações de Água e Esgoto", 
                'template_sid': 'HX72176f6bb644719b83ff4d283ea1d586', 
                'proximo': 'AGUARDANDO_HABILIDADE_3'
            },
            '3': {
                'id_habilidade': 3, 
                'descricao': "Combate a Fraudes", 
                'template_sid': 'HX6bdb1435da31742cca8cc7b1bbe3ce99', 
                'proximo': 'AGUARDANDO_HABILIDADE_4'
            },
            '4': {
                'id_habilidade': 4, 
                'descricao': "Verificação de Consumo", 
                'template_sid': 'HXa4e41567c8dac4b573ac4d940df58249', 
                'proximo': 'AGUARDANDO_HABILIDADE_5'
            },
            '5': {
                'id_habilidade': 5, 
                'descricao': "Manutenção da Rede de Esgoto na Rua", 
                'template_sid': 'HXdba84c0e8c46f2de94464e4f2468c213', 
                'proximo': 'AGUARDANDO_HABILIDADE_7' 
            },
            '7': {
                'id_habilidade': 7, 
                'descricao': "Operação Rede Distribuição", 
                'template_sid': 'HX080222a6097b808579c11838b278959d', 
                'proximo': 'AGUARDANDO_HABILIDADE_8'
            },
            '8': {
                'id_habilidade': 8, 
                'descricao': "Cadastro", 
                'template_sid': 'HX4ec2c189146a69807ee842bac9f056de',
                'proximo': 'INICIAR_VEICULOS'
            }
        }

    def _gerar_resposta_template(self, proximo_passo, template_sid):
        return proximo_passo, {
            'tipo': 'template',
            'sid': template_sid, 
            'variaveis': {}
        }

    # 🟢 O MÉTODO QUE FALTAVA FOI ADICIONADO AQUI 👇
    def reenviar_etapa_atual(self, step_atual):
        """
        Recupera o template da etapa atual para permitir a retomada (resume)
        sem precisar avançar o fluxo.
        """
        try:
            step_key = step_atual.split('_')[-1] # Ex: Pega '5' de AGUARDANDO_HABILIDADE_5
            config = self.FLUXO.get(step_key)
            if config:
                return self._gerar_resposta_template(step_atual, config['template_sid'])
        except:
            pass
        return None

    def _salvar_background(self, id_habilidade, sender_id):
        try:
            sql = "INSERT INTO PARCEIROS_HABILIDADES (HabilidadeID, ParceiroUUID, TipoServicoID, TempoExperiencia) SELECT NEWID(), P.ParceiroUUID, ?, NULL FROM PARCEIROS_PERFIL P WHERE P.WhatsAppID = ? AND NOT EXISTS (SELECT 1 FROM PARCEIROS_HABILIDADES PH WHERE PH.ParceiroUUID = P.ParceiroUUID AND PH.TipoServicoID = ?)"
            self.db.execute_write(sql, (id_habilidade, sender_id, id_habilidade))
            print(f"✅ [Background] Habilidade {id_habilidade} processada")
        except Exception as e:
            print(f"🔥 [Background Erro] {e}")

    def iniciar_modulo(self, sender_id):
        config_q1 = self.FLUXO['1']
        return self._gerar_resposta_template('AGUARDANDO_HABILIDADE_1', config_q1['template_sid'])

    def processar_resposta(self, step_atual, texto, sender_id):
        try:
            step_key = step_atual.split('_')[-1]
            config_atual = self.FLUXO.get(step_key)
        except: return step_atual, {'tipo': 'texto', 'conteudo': "Erro interno."}

        if not config_atual: return step_atual, {'tipo': 'texto', 'conteudo': "Configuração não encontrada."}

        resp_clean = texto.strip().upper()
        if resp_clean not in ['SIM', 'S', 'NAO', 'NÃO', 'N']:
            return step_atual, {'tipo': 'texto', 'conteudo': "⚠️ Resposta inválida. Use os botões SIM ou NÃO."}

        if resp_clean in ['SIM', 'S']:
            threading.Thread(target=self._salvar_background, args=(config_atual['id_habilidade'], sender_id)).start()

        proximo_step = config_atual['proximo']
        
        if proximo_step == 'INICIAR_VEICULOS':
            # Agora chamamos especificamente o passo do CARRO
            return 'AGUARDANDO_VEICULO_CARRO', {
                'tipo': 'sequencia',
                'mensagens': [
                    {'tipo': 'texto', 'conteudo': "🛠️ Habilidades registradas!", 'delay': 1},
                    {'tipo': 'texto', 'conteudo': "🚗 *Nova Etapa: Veículos*\n\nAgora vamos falar sobre seu transporte.", 'delay': 2},
                    {
                        'tipo': 'template',
                        'sid': self.TEMPLATE_VEICULOS, 
                        'variaveis': {},
                        'delay': 1
                    }
                ]
            }

        prox_key = proximo_step.split('_')[-1]
        return self._gerar_resposta_template(proximo_step, self.FLUXO[prox_key]['template_sid'])