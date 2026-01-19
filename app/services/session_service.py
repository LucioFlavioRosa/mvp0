from app.core.database import DatabaseManager

class SessionService:
    def __init__(self):
        self.db = DatabaseManager()

    def verificar_entrada_usuario(self, whatsapp_id):
        """
        Define o estado do usuário.
        Regra de Ouro: Se existir um perfil RASCUNHO, o usuário SEMPRE 
        será convidado a continuar, independente de como terminou a conversa anterior.
        """
        # 1. Busca passo atual da sessão
        row_session = self.db.execute_read_one("SELECT CurrentStep FROM CHAT_SESSIONS WHERE WhatsAppID=?", (whatsapp_id,))
        current_step = row_session[0] if row_session else None

        # 2. Busca status do perfil
        row_profile = self.db.execute_read_one("SELECT StatusAtual FROM PARCEIROS_PERFIL WHERE WhatsAppID=?", (whatsapp_id,))
        
        # Variáveis auxiliares
        tem_perfil = row_profile is not None
        status_perfil = row_profile[0] if row_profile else None
        
        # Passos que consideramos "sessão inativa"
        passos_neutros = ['START', 'FINALIZADO', 'DECISAO_REFAZER', 'DECISAO_CONTINUAR', 'CHECK_DEVICE_RESPOSTA']

        # --- REGRA 1: Sessão Ativa (Usuário estava digitando agora pouco) ---
        # Se ele está num passo ativo (ex: AGUARDANDO_CPF), mantemos o fluxo.
        if current_step and current_step not in passos_neutros:
             return {'tipo': 'CADASTRO_ANDAMENTO'}

        # --- REGRA 2: Verificação de Perfil (Memória de Longo Prazo) ---
        if tem_perfil:
            if status_perfil in ['ATIVO', 'EM_ANALISE']:
                return {'tipo': 'CADASTRO_COMPLETO'}
            
            # AQUI ESTÁ A CORREÇÃO:
            # Se o status NÃO é completo (ou seja, é RASCUNHO ou NULL),
            # nós tratamos como ANDAMENTO, mesmo que a sessão esteja FINALIZADA.
            else:
                return {'tipo': 'CADASTRO_ANDAMENTO'}

        # --- REGRA 3: Sem perfil e Sem sessão ---
        return {'tipo': 'NOVO_USUARIO'}

    def iniciar_nova_sessao(self, whatsapp_id):
        self.db.execute_write("DELETE FROM CHAT_SESSIONS WHERE WhatsAppID=?", (whatsapp_id,))
        self.db.execute_write(
            "INSERT INTO CHAT_SESSIONS (WhatsAppID, CurrentStep, LastUpdate) VALUES (?, 'START', GETDATE())",
            (whatsapp_id,)
        )

    def arquivar_usuario_antigo(self, whatsapp_id):
        import uuid
        novo_id = f"{whatsapp_id}_v{str(uuid.uuid4())[:4]}"
        
        sqls = [
            ("UPDATE PARCEIROS_PERFIL SET WhatsAppID=? WHERE WhatsAppID=?", (novo_id, whatsapp_id)),
            ("UPDATE CHAT_SESSIONS SET WhatsAppID=? WHERE WhatsAppID=?", (novo_id, whatsapp_id))
        ]
        self.db.execute_transaction(sqls)