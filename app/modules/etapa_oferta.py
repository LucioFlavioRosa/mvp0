from app.core.database import DatabaseManager

class EtapaOferta:
    def __init__(self):
        self.db = DatabaseManager()

    def verificar_oferta_pendente(self, whatsapp_id):
        sql = """
        SELECT TOP 1 d.DisparoID, d.PedidoID
        FROM PEDIDOS_DISPAROS d
        JOIN PARCEIROS_PERFIL p ON d.ParceiroUUID = p.ParceiroUUID
        WHERE p.WhatsAppID = ? 
          AND d.Status = 'ENVIADO'
        ORDER BY d.DataAtualizacao DESC
        """
        return self.db.execute_read_one(sql, (whatsapp_id,))

    def processar_resposta(self, texto, dados_oferta, sender_id):
        resposta = texto.strip().upper()
        disparo_id, pedido_id = dados_oferta 
        
        if not pedido_id or not disparo_id:
            return 'START', {'tipo': 'texto', 'conteudo': "❌ Erro: Dados da oferta inválidos."}

        # ======================================================================
        # SIM (ACEITE)
        # ======================================================================
        if resposta in ['SIM', 'S', 'ACEITO', 'QUERO']:
            
            # 1. Verifica Concorrência
            sql_check = "SELECT 1 FROM ORDENS_SERVICO WHERE PedidoID = ?"
            ja_pegaram = self.db.execute_read_one(sql_check, (pedido_id,))
            
            if ja_pegaram:
                # Se o banco der erro de constraint, mude 'ACEITE_ATRASADO' para 'CANCELADO'
                self.db.execute_write("UPDATE PEDIDOS_DISPAROS SET Status='ACEITE_ATRASADO', DataAtualizacao=GETDATE() WHERE DisparoID=?", (disparo_id,))
                return 'AGUARDANDO_NOVA_OFERTA', {'tipo': 'texto', 'conteudo': "⚠️ **Infelizmente você chegou tarde!**\n\nOutro parceiro foi mais rápido. Mas registramos seu interesse e vamos continuar te enviando oportunidades!"}
            
            # 2. Busca UUID do parceiro
            row_uuid = self.db.execute_read_one("SELECT ParceiroUUID FROM PARCEIROS_PERFIL WHERE WhatsAppID=?", (sender_id,))
            parceiro_uuid = row_uuid[0] if row_uuid else None
            
            if not parceiro_uuid:
                return 'START', {'tipo': 'texto', 'conteudo': "Erro interno de cadastro."}

            # 🟢 3. CRIA A ORDEM (SQL LIMPO - SEM Geo e SLA)
            sql_insert_ordem = """
            INSERT INTO ORDENS_SERVICO 
            (
                OrdemID, 
                PedidoID, 
                ParceiroAlocadoUUID, 
                StatusOrdem, 
                TipoServicoID
            )
            SELECT 
                NEWID(), 
                p.PedidoID, 
                ?,               
                'ABERTA', 
                p.TipoServicoID
            FROM PEDIDOS_SERVICO p
            WHERE p.PedidoID = ?
            """
            
            sucesso = self.db.execute_write(sql_insert_ordem, (parceiro_uuid, pedido_id))
            
            if sucesso:
                # A) Atualiza status do disparo para ACEITO
                self.db.execute_write("UPDATE PEDIDOS_DISPAROS SET Status='ACEITO', DataAtualizacao=GETDATE() WHERE DisparoID=?", (disparo_id,))
                
                # B) Atualiza o Pedido Principal para VINCULADO
                self.db.execute_write("UPDATE PEDIDOS_SERVICO SET StatusPedido='VINCULADO' WHERE PedidoID=?", (pedido_id,))
                
                # C) Sequência de mensagens
                msg_agradecimento = (
                    "🎉 *Obrigado por aceitar o serviço, você foi selecionado para execução!*\n\n"
                    "Por favor, quando chegar no local para a execução do serviço, siga as instruções que enviaremos a seguir "
                    "para garantirmos seu pagamento no prazo combinado."
                )

                msg_instrucoes = (
                    "*Tudo certo! Siga este passo a passo para garantir a validação do seu serviço:*\n\n"
                    "✅ *Chegou no local?* Ative o GPS do seu celular imediatamente.\n"
                    "✅ *Configuração:* Confirme se sua câmera está salvando as informações de localização nas fotos.\n"
                    "✅ *Localização:* Envie sua localização atual pelo WhatsApp antes de iniciar.\n"
                    "✅ *Foto Inicial:* Tire a foto antes de começar o trabalho, usando a câmera nativa do celular (Não tire a foto direto pelo WhatsApp).\n"
                    "✅ *Envio Seguro:* Envie a foto como *DOCUMENTO* para preservarmos o GPS e o horário.\n"
                    "✅ *Finalização:* Repita o processo de tirar a foto e envio da foto e localização ao concluir o trabalho.\n\n"
                    "*Pode começar! Bom trabalho.* 🚀"
                )

                return 'EM_SERVICO', {
                    'tipo': 'sequencia',
                    'mensagens': [
                        {'tipo': 'texto', 'conteudo': msg_agradecimento, 'delay': 1}, 
                        {'tipo': 'texto', 'conteudo': msg_instrucoes, 'delay': 10}
                    ]
                }
            else:
                 return 'START', {'tipo': 'texto', 'conteudo': "Erro técnico ao registrar a ordem. (Falha de Insert)"}

        # ======================================================================
        # NÃO (RECUSA)
        # ======================================================================
        elif resposta in ['NAO', 'NÃO', 'N', 'RECUSAR']:
            self.db.execute_write("UPDATE PEDIDOS_DISPAROS SET Status='NEGADO', DataAtualizacao=GETDATE() WHERE DisparoID=?", (disparo_id,))
            return 'AGUARDANDO_NOVA_OFERTA', {'tipo': 'texto', 'conteudo': "👍 Sem problemas. Continuamos procurando serviços para você."}
        
        else:
            return 'AGUARDANDO_RESPOSTA', {'tipo': 'texto', 'conteudo': "Não entendi. Digite **SIM** para aceitar ou **NÃO** para recusar."}