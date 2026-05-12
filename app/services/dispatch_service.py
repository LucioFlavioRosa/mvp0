from datetime import datetime
from app.core.database import DatabaseManager
from app.services.whatsapp_service import WhatsAppService

class DispatchService:
    def __init__(self):
        self.db = DatabaseManager()
        self.whatsapp = WhatsAppService()

        # Nome do template cadastrado no portal Infobip.
        # ⚠ REVISAR MANUALMENTE: cadastrar o template no portal antes do deploy
        # (mesmos 9 placeholders na ordem nome/atividade/numero/rua/bairro/data/obs/valor/urgencia)
        # e ajustar este nome para o que foi definido no portal.
        self.TEMPLATE_OFERTA = "oferta_servico"

    def enviar_oferta_para_prestadores(self, lista_uuids, pedido_uuid):
        """
        Busca dados detalhados do pedido e notifica a lista de prestadores
        registrando o disparo na tabela PEDIDOS_DISPAROS.
        """
        
        # 1. Busca dados na tabela PEDIDOS_SERVICO
        sql_pedido = """
            SELECT 
                Atividade, Rua, Numero, Bairro, DataLimite, Observacao, Valor, Urgencia
            FROM PEDIDOS_SERVICO 
            WHERE PedidoID = ?
        """
        row_pedido = self.db.execute_read_one(sql_pedido, (pedido_uuid,))
        
        if not row_pedido:
            return {"status": "error", "message": f"Pedido {pedido_uuid} não encontrado"}

        atividade, rua, numero, bairro, data_limite_raw, observacao, valor, urgencia = row_pedido

        # Tratamento de Nulos
        atividade = atividade or "Serviço Geral"
        rua = rua or "Rua não informada"
        numero = numero or "S/N"
        bairro = bairro or "Bairro não informado"
        observacao = observacao or "Verificar detalhes no app"
        valor = valor or 0.0
        urgencia = urgencia or "Normal"

        valor_fmt = f"{valor:.2f}".replace('.', ',')
        data_fmt = data_limite_raw.strftime('%d/%m/%Y') if isinstance(data_limite_raw, datetime) else str(data_limite_raw or "A combinar")

        count_envios = 0

        # 2. Loop pelos Parceiros
        for parceiro_uuid in lista_uuids:
            sql_user = "SELECT WhatsAppID, NomeCompleto FROM PARCEIROS_PERFIL WHERE ParceiroUUID = ?"
            row_user = self.db.execute_read_one(sql_user, (parceiro_uuid,))
            
            if row_user:
                whatsapp_id, nome_parceiro = row_user
                primeiro_nome = nome_parceiro.split()[0] if nome_parceiro else "Parceiro"

                # 🟢 A) REGISTRA O DISPARO (PEDIDOS_DISPAROS)
                # Não tocamos mais na CHAT_SESSIONS
                sql_disparo = """
                INSERT INTO PEDIDOS_DISPAROS (PedidoID, ParceiroUUID, Status, DataAtualizacao)
                VALUES (?, ?, 'ENVIADO', GETDATE())
                """
                sucesso_db = self.db.execute_write(sql_disparo, (pedido_uuid, parceiro_uuid))

                if sucesso_db:
                    # B) MONTA PLACEHOLDERS (lista posicional, padrão Infobip)
                    placeholders = [
                        primeiro_nome,
                        atividade,
                        str(numero),
                        rua,
                        bairro,
                        data_fmt,
                        observacao,
                        valor_fmt,
                        urgencia,
                    ]

                    # C) ENVIA WHATSAPP
                    msg_template = {
                        'tipo': 'template',
                        'template_name': self.TEMPLATE_OFERTA,
                        'placeholders': placeholders,
                    }

  