from app.services.session_service import SessionService

class ModuloOnboarding:
    def __init__(self):
        self.service = SessionService()
        
        # SIDs dos Templates
        self.TEMPLATE_CONTINUAR = 'HX561c6dcac03b3f14b710ac0f02038813' 
        self.TEMPLATE_REFAZER   = 'HXf09134b49fb98aab9718a796df2ac491' 
        self.TEMPLATE_CHECK     = 'HXab1915d077dc69d3a0e124e42fabff46' 
        
        # Mensagem Padrão de Erro
        self.MSG_ERRO_CANAL = "⚠️ Não entendi sua resposta. Este canal é exclusivo para cadastro no Programa Águas do Pará.\n\nPor favor, responda apenas utilizando os botões ou com SIM/NÃO."

    def processar_inicio(self, sender_id):
        estado = self.service.verificar_entrada_usuario(sender_id)
        tipo = estado['tipo']
        
        msg_boas_vindas = "👋 Olá! Seja bem-vindo! Estou aqui para te ajudar a fazer seu cadastro no projeto Águas do Pará."

        if tipo == 'CADASTRO_COMPLETO':
            return 'DECISAO_REFAZER', {
                'tipo': 'combo_inicial',
                'texto': f"{msg_boas_vindas}",
                'template_sid': self.TEMPLATE_REFAZER, 
                'variaveis': {}
            }
        
        elif tipo == 'CADASTRO_ANDAMENTO':
            return 'DECISAO_CONTINUAR', {
                'tipo': 'combo_inicial',
                'texto': f"{msg_boas_vindas}",
                'template_sid': self.TEMPLATE_CONTINUAR,
                'variaveis': {}
            }

        else: 
            # 🟢 MUDANÇA AQUI: Usamos 'sequencia' para aplicar o delay de 10s
            return 'CHECK_DEVICE_RESPOSTA', {
                'tipo': 'sequencia',
                'mensagens': [
                    {
                        'tipo': 'texto',
                        'conteudo': f"{msg_boas_vindas}\n\nFicamos muito felizes com seu interesse em ser nosso parceiro! Vamos iniciar seu cadastro.",
                        'delay': 1 # Envia o texto quase imediatamente
                    },
                    {
                        'tipo': 'template',
                        'sid': self.TEMPLATE_CHECK,
                        'variaveis': {},
                        'delay': 10 # ⏳ Espera 10 segundos antes de mandar a pergunta do celular
                    }
                ]
            }

    def processar_decisao_refazer(self, texto, sender_id):
        """
        Lida com 'Quer começar do zero?'.
        """
        resp = texto.strip().upper()
        
        # 1. Opção SIM (Refazer)
        if resp in ['SIM', 'S', 'QUERO', 'REFAZER', 'YES']:
            self.service.arquivar_usuario_antigo(sender_id)
            
            return 'CHECK_DEVICE_RESPOSTA', {
                'tipo': 'combo_inicial',
                'texto': "🔄 Perfeito! Cadastro antigo arquivado. Vamos começar.",
                'template_sid': self.TEMPLATE_CHECK,
                'variaveis': {}
            }
        
        # 2. Opção NÃO (Sair/Manter antigo)
        elif resp in ['NAO', 'NÃO', 'N', 'NO', 'NUNCA']:
            return 'FINALIZADO', {
                'tipo': 'texto', 
                'conteudo': "Tudo bem! Seu cadastro atual permanece salvo. Até mais! 👋"
            }
            
        # 3. Resposta Inesperada
        else:
            return 'DECISAO_REFAZER', {
                'tipo': 'texto',
                'conteudo': self.MSG_ERRO_CANAL
            }

    def processar_decisao_continuar(self, texto, sender_id):
        resp = texto.strip().upper()
        
        # 1. Opção SIM (Continuar)
        if resp in ['SIM', 'S', 'CONTINUAR', 'YES', 'QUERO']:
            return 'RETOMAR_FLUXO', {}
            
        # 2. Opção NÃO (Não continuar -> Oferece Refazer)
        elif resp in ['NAO', 'NÃO', 'N', 'NO']:
            return 'DECISAO_REFAZER', {
                'tipo': 'combo_inicial',
                'texto': "Entendido. Nesse caso, você gostaria de **começar o cadastro do zero**?",
                'template_sid': self.TEMPLATE_REFAZER,
                'variaveis': {}
            }
            
        # 3. Resposta Inesperada
        else:
            return 'DECISAO_CONTINUAR', {
                'tipo': 'texto',
                'conteudo': self.MSG_ERRO_CANAL
            }

    def processar_check_device(self, texto, sender_id):
        resp = texto.strip().upper()
        
        # 1. Opção SIM (Tem device)
        if resp in ['SIM', 'S', 'TENHO', 'YES']:
             # O BotEngine atualizará automaticamente o step para AGUARDANDO_CNPJ
             return 'AGUARDANDO_CNPJ', {
                 'tipo': 'texto', 
                 'conteudo': "✅ Ótimo! Para iniciar, digite o número do seu *CNPJ* (apenas números):"
             }
        
        # 2. Opção NÃO (Não tem device -> Finaliza)
        elif resp in ['NAO', 'NÃO', 'N', 'NO', 'NUNCA']:
             return 'FINALIZADO', {
                 'tipo': 'texto', 
                 'conteudo': "❌ Agradecemos o interesse, mas os requisitos de celular e internet são obrigatórios para o projeto."
             }
             
        # 3. Resposta Inesperada
        else:
             return 'CHECK_DEVICE_RESPOSTA', {
                 'tipo': 'texto',
                 'conteudo': self.MSG_ERRO_CANAL
             }