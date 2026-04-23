from app.core.database import DatabaseManager
from app.services.infra.azure_blob_service import AzureBlobService

class EtapaDocumentos:
    def __init__(self):
        self.db = DatabaseManager()
        self.blob_service = AzureBlobService()
        
        # SIDs dos Templates
        self.TEMPLATE_ESCOLHA_DOC = "HX725fe0933cb5a8ab346c2afe1e05471f" 
        self.TEMPLATE_TERMOS      = "HXe1df7a89a7b55e71b26a06cd2e601ec7" 
        
    def iniciar_modulo(self, sender_id):
        return 'AGUARDANDO_TIPO_DOC', {
            'tipo': 'template',
            'sid': self.TEMPLATE_ESCOLHA_DOC,
            'variaveis': {}
        }

    # 🟢 Retomada Inteligente
    def reenviar_etapa_atual(self, step_atual):
        # 1. Menu de Escolha (CNH ou RG)
        if step_atual in ['AGUARDANDO_TIPO_DOC', 'INICIAR_DOCUMENTOS']:
            return 'AGUARDANDO_TIPO_DOC', {
                'tipo': 'template',
                'sid': self.TEMPLATE_ESCOLHA_DOC,
                'variaveis': {}
            }
        
        # 2. Upload de Fotos (Frente)
        if step_atual == 'AGUARDANDO_FRENTE_CNH':
            return step_atual, {'tipo': 'texto', 'conteudo': "🔄 Retomando: Envie a foto da **FRENTE** da sua CNH:"}
        
        if step_atual == 'AGUARDANDO_FRENTE_RG':
            return step_atual, {'tipo': 'texto', 'conteudo': "🔄 Retomando: Envie a foto da **FRENTE** do seu RG:"}
        
        # 3. Upload de Fotos (Verso)
        if step_atual == 'AGUARDANDO_VERSO_CNH':
            return step_atual, {'tipo': 'texto', 'conteudo': "🔄 Retomando: Agora envie a foto do **VERSO** da CNH:"}
        
        if step_atual == 'AGUARDANDO_VERSO_RG':
            return step_atual, {'tipo': 'texto', 'conteudo': "🔄 Retomando: Agora envie a foto do **VERSO** do RG:"}
        
        # 4. Selfie
        if step_atual == 'AGUARDANDO_SELFIE':
            return step_atual, {'tipo': 'texto', 'conteudo': "🔄 Retomando: Envie sua **SELFIE** segurando o documento:"}
        
        # 5. PIX
        if step_atual == 'AGUARDANDO_PIX':
            return step_atual, {'tipo': 'texto', 'conteudo': "🔄 Retomando: Digite sua chave **PIX** para recebimento:"}
        
        # 6. Termos (Template)
        if step_atual == 'AGUARDANDO_TERMOS':
            return step_atual, {
                'tipo': 'template',
                'sid': self.TEMPLATE_TERMOS,
                'variaveis': {}
            }
            
        return None

    def processar_resposta(self, step_atual, texto, media_url, sender_id):
        texto = texto.strip().upper() if texto else ""
        
        # ======================================================================
        # 1. ESCOLHA DO TIPO DE DOCUMENTO
        # ======================================================================
        if step_atual == 'AGUARDANDO_TIPO_DOC':
            if 'CNH' in texto:
                return 'AGUARDANDO_FRENTE_CNH', {'tipo': 'texto', 'conteudo': "📸 Por favor, envie uma foto da **FRENTE** da sua CNH (aberta, se possível)."}
            elif 'IDENTIDADE' in texto or 'RG' in texto:
                return 'AGUARDANDO_FRENTE_RG', {'tipo': 'texto', 'conteudo': "📸 Por favor, envie uma foto da **FRENTE** da sua Identidade (RG)."}
            else:
                return step_atual, {'tipo': 'texto', 'conteudo': "⚠️ Opção inválida. Escolha **CNH** ou **Identidade**."}

        # ======================================================================
        # 2. UPLOAD DE FOTOS (FRENTE)
        # ======================================================================
        if step_atual in ['AGUARDANDO_FRENTE_CNH', 'AGUARDANDO_FRENTE_RG']:
            if not media_url:
                return step_atual, {'tipo': 'texto', 'conteudo': "⚠️ Preciso que você envie uma **FOTO** (imagem). Tente novamente."}
            
            eh_cnh = 'CNH' in step_atual
            container = 'cnh' if eh_cnh else 'identidade'
            tipo_doc_db = 'CNH' if eh_cnh else 'IDENTIDADE'
            
            uuid = self._get_uuid(sender_id)
            if not uuid: return 'START', {'tipo': 'texto', 'conteudo': "Erro de sessão."}

            path_blob = f"{uuid}/frente.jpg"
            
            # Tenta Upload
            url_azure = self.blob_service.upload_from_url(media_url, container, path_blob)
            
            if url_azure:
                # ✅ SUCESSO: Salva doc e AVANÇA para o próximo passo
                self._salvar_doc_db(uuid, tipo_doc_db, url_azure)
                proximo = 'AGUARDANDO_VERSO_CNH' if eh_cnh else 'AGUARDANDO_VERSO_RG'
                return proximo, {'tipo': 'texto', 'conteudo': "✅ Frente recebida! Agora envie uma foto do **VERSO** (Parte de trás)."}
            else:
                # ❌ FALHA: Retorna step_atual (BotEngine NÃO atualiza o banco para o próximo passo)
                return step_atual, {'tipo': 'texto', 'conteudo': "❌ Falha ao salvar imagem no servidor. Tente enviar novamente."}

        # ======================================================================
        # 3. UPLOAD DE FOTOS (VERSO)
        # ======================================================================
        if step_atual in ['AGUARDANDO_VERSO_CNH', 'AGUARDANDO_VERSO_RG']:
            if not media_url:
                return step_atual, {'tipo': 'texto', 'conteudo': "⚠️ Preciso da foto do verso."}

            eh_cnh = 'CNH' in step_atual
            container = 'cnh' if eh_cnh else 'identidade'
            tipo_doc_db = 'CNH' if eh_cnh else 'IDENTIDADE'
            
            uuid = self._get_uuid(sender_id)
            path_blob = f"{uuid}/verso.jpg" 
            
            # Tenta Upload
            url_azure = self.blob_service.upload_from_url(media_url, container, path_blob)

            if url_azure:
                # ✅ SUCESSO: Avança
                self._salvar_doc_db(uuid, tipo_doc_db, url_azure)
                return 'AGUARDANDO_SELFIE', {'tipo': 'texto', 'conteudo': "✅ Documento salvo!\n\nAgora, envie uma **SELFIE** sua segurando o documento (ao lado do rosto)."}
            else:
                # ❌ FALHA: Mantém no passo atual
                return step_atual, {'tipo': 'texto', 'conteudo': "❌ Erro no upload do verso. Tente de novo."}

        # ======================================================================
        # 4. SELFIE
        # ======================================================================
        if step_atual == 'AGUARDANDO_SELFIE':
            if not media_url:
                return step_atual, {'tipo': 'texto', 'conteudo': "⚠️ Por favor, envie a foto da selfie."}

            uuid = self._get_uuid(sender_id)
            path_blob = f"{uuid}/selfie.jpg"
            
            # Tenta Upload
            url_azure = self.blob_service.upload_from_url(media_url, 'selfie', path_blob)
            
            if url_azure:
                # ✅ SUCESSO: Avança
                self._salvar_doc_db(uuid, 'SELFIE', url_azure)
                return 'AGUARDANDO_PIX', {'tipo': 'texto', 'conteudo': "📸 Selfie recebida!\n\nAgora digite sua **Chave PIX** para recebimento:"}
            else:
                # ❌ FALHA: Mantém no passo atual (Adicionei este else que faltava)
                return step_atual, {'tipo': 'texto', 'conteudo': "❌ Erro ao salvar a Selfie. Tente enviar novamente."}
            
        # ======================================================================
        # 5. PIX
        # ======================================================================
        if step_atual == 'AGUARDANDO_PIX':
            if media_url:
                return step_atual, {'tipo': 'texto', 'conteudo': "⚠️ Por favor, digite a chave PIX em texto."}
            
            self._atualizar_perfil(sender_id, chave_pix=texto)
            return 'AGUARDANDO_TERMOS', {
                'tipo': 'template',
                'sid': self.TEMPLATE_TERMOS,
                'variaveis': {}
            }

        # ======================================================================
        # 6. TERMOS
        # ======================================================================
        if step_atual == 'AGUARDANDO_TERMOS':
            if texto in ['SIM', 'S', 'ACEITO']:
                self._atualizar_perfil(sender_id, aceite=1, status='EM_ANALISE')
                return 'FINALIZADO', {'tipo': 'texto', 'conteudo': "🎉 **Cadastro Finalizado!**\n\nRecebemos seus dados e documentos. Nossa equipe fará a análise e entraremos em contato em breve.\n\nObrigado por fazer parte do projeto Águas do Pará!"}
            else:
                return 'FINALIZADO_SEM_ACEITE', {'tipo': 'texto', 'conteudo': "⚠️ Entendido. Precisamos do aceite para prosseguir. Se mudar de ideia, digite OI para retomar."}

        return step_atual, {'tipo': 'texto', 'conteudo': "Não entendi."}

    # ==========================================================================
    # HELPERS DE BANCO DE DADOS
    # ==========================================================================
    def _get_uuid(self, whatsapp_id):
        res = self.db.execute_read_one("SELECT ParceiroUUID FROM PARCEIROS_PERFIL WHERE WhatsAppID = ?", (whatsapp_id,))
        return res[0] if res else None

    def _salvar_doc_db(self, uuid, tipo, blob_path):
        sql = """
        INSERT INTO PARCEIROS_DOCS_LEGAIS (ParceiroUUID, TipoDocumento, BlobPath, StatusValidacao)
        VALUES (?, ?, ?, 'PENDENTE')
        """
        self.db.execute_write(sql, (uuid, tipo, blob_path))

    def _atualizar_perfil(self, whatsapp_id, chave_pix=None, aceite=None, status=None):
        if chave_pix:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET chave_pix = ? WHERE WhatsAppID = ?", (chave_pix, whatsapp_id))
        
        if aceite is not None:
             self.db.execute_write("UPDATE PARCEIROS_PERFIL SET Aceite = ?, StatusAtual = ? WHERE WhatsAppID = ?", (aceite, status, whatsapp_id))