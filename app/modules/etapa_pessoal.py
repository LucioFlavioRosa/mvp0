from app.modules.common import GeradorResposta
from app.core.database import DatabaseManager
import re
import random
from app.core.config import Settings

class EtapaPessoal:
    def __init__(self):
        self.db = DatabaseManager()

    # 🟢 Método de Retomada Inteligente
    def reenviar_etapa_atual(self, step_atual):
        if step_atual == 'AGUARDANDO_CNPJ':
            return step_atual, {
                'tipo': 'texto',
                'conteudo': "🔄 Vamos retomar o cadastro.\n\nPor favor, digite o número do seu *CNPJ* (apenas números):"
            }
        elif step_atual == 'AGUARDANDO_CPF':
            return step_atual, {
                'tipo': 'texto',
                'conteudo': "🔄 Retomando validação.\n\nPor favor, digite o seu *CPF* (apenas números):"
            }
        elif step_atual == 'AGUARDANDO_NOME':
            return step_atual, {
                'tipo': 'texto',
                'conteudo': "🔄 Retomando.\n\nPor favor, digite seu *Nome Completo*:"
            }
        return None

    def processar_cnpj(self, texto, sender_id):
        # 1. VALIDAÇÃO DE FORMATO
        cnpj_limpo = re.sub(r'[^a-zA-Z0-9]', '', texto).upper()
        
        if len(cnpj_limpo) != 14:
            msg_erro = f"❌ *Formato incorreto!*\nO CNPJ deve ter 14 caracteres. Recebi {len(cnpj_limpo)}.\nEnvie novamente:"
            return 'AGUARDANDO_CNPJ', {'tipo': 'texto', 'conteudo': msg_erro}

        # 2. PERSISTÊNCIA (MERGE)
        sql = """
        MERGE PARCEIROS_PERFIL AS target
        USING (SELECT ? AS WhatsAppID) AS source
        ON (target.WhatsAppID = source.WhatsAppID)
        WHEN MATCHED THEN
            UPDATE SET CNPJ = ?
        WHEN NOT MATCHED THEN
            INSERT (WhatsAppID, CNPJ) VALUES (?, ?);
        """
        sucesso = self.db.execute_write(sql, (sender_id, cnpj_limpo, sender_id, cnpj_limpo))

        if not sucesso:
            return 'AGUARDANDO_CNPJ', {'tipo': 'texto', 'conteudo': "⚠️ Falha técnica ao salvar CNPJ. Tente novamente."}

        # 3. PREPARAÇÃO DA MENSAGEM
        settings = Settings()
        base_url = settings.get_secret('APP_BASE_URL') or ''
        url_video = f"{base_url}/apresentacao.mp4" if base_url else "apresentacao.mp4"

        lista_mensagens = [
            {
                'tipo': 'texto',
                'conteudo': f"⏳ Recebemos o CNPJ *{cnpj_limpo}*.\n\nEstamos consultando as bases governamentais para validação.\nEnquanto aguarda, assista ao nosso vídeo de apresentação:",
                'delay': 1 
            },
            {
                'tipo': 'media',
                'url': url_video,
                'legenda': "",
                'delay': 2 
            }
        ]

        # 4. VALIDAÇÃO (90% CHANCE)
        chance = random.random()
        aprovado = chance < 0.99
        print(f"🎲 Validação CNPJ: {aprovado}")

        if aprovado:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET StatusAtual='EM_ANALISE' WHERE WhatsAppID=?", (sender_id,))

            lista_mensagens.append({
                'tipo': 'texto',
                'conteudo': "✅ *CNPJ Validado com Sucesso!*\n\nConsulta realizada e aprovada.\n\n👇 Agora, digite seu *CPF* (apenas números) para prosseguir:",
                'delay': 30
            })
            return 'AGUARDANDO_CPF', {'tipo': 'sequencia', 'mensagens': lista_mensagens}
            
        else:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET StatusAtual='CNPJ_REJEITADO' WHERE WhatsAppID=?", (sender_id,))
            
            lista_mensagens.append({
                'tipo': 'texto',
                'conteudo': "❌ *Cadastro Não Aprovado*\n\nInfelizmente identificamos pendências cadastrais.\nAgradecemos seu interesse.",
                'delay': 5
            })
            return 'FINALIZADO', {'tipo': 'sequencia', 'mensagens': lista_mensagens}

    def processar_cpf(self, texto, sender_id):
        # 1. LIMPEZA
        cpf_limpo = re.sub(r'\D', '', texto)
        
        # 2. VALIDAÇÃO DE FORMATO
        if len(cpf_limpo) != 11:
            msg_erro = f"❌ *CPF Inválido!*\nO CPF deve ter 11 números. Recebi {len(cpf_limpo)}.\nPor favor, digite novamente:"
            return 'AGUARDANDO_CPF', {'tipo': 'texto', 'conteudo': msg_erro}
        
        # 3. PERSISTÊNCIA
        sucesso = self.db.execute_write("UPDATE PARCEIROS_PERFIL SET CPF=? WHERE WhatsAppID=?", (cpf_limpo, sender_id))
        
        if not sucesso:
             return 'AGUARDANDO_CPF', {'tipo': 'texto', 'conteudo': "⚠️ Erro técnico ao salvar CPF. Tente novamente."}

        # 4. PREPARA SEQUÊNCIA
        lista_mensagens = [
            {'tipo': 'texto', 'conteudo': f"🔍 Validando o CPF *{cpf_limpo}* na Receita Federal...", 'delay': 2}
        ]

        # 5. SIMULAÇÃO DE VALIDAÇÃO
        chance = random.random()
        aprovado = chance < 0.99
        print(f"🎲 Validação CPF: {aprovado}")

        if aprovado:
            lista_mensagens.append({
                'tipo': 'texto',
                'conteudo': "✅ *CPF Aprovado!*\n\nAgora digite seu *Nome Completo*:",
                'delay': 5 
            })
            return 'AGUARDANDO_NOME', {'tipo': 'sequencia', 'mensagens': lista_mensagens}

        else:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET StatusAtual='CPF_REJEITADO' WHERE WhatsAppID=?", (sender_id,))
            lista_mensagens.append({
                'tipo': 'texto',
                'conteudo': "❌ *CPF Não Aprovado*\n\nIdentificamos restrições neste CPF que impedem o prosseguimento do cadastro.\nAgradecemos o interesse.",
                'delay': 2
            })
            return 'FINALIZADO', {'tipo': 'sequencia', 'mensagens': lista_mensagens}

    def processar_nome(self, texto, sender_id):
        nome = texto.strip()
        
        # 1. Validação de tamanho mínimo
        if len(nome) < 3:
            return 'AGUARDANDO_NOME', {'tipo': 'texto', 'conteudo': "Nome muito curto. Digite seu nome completo:"}
            
        # 🟢 2. Validação de Nome Composto (Pelo menos 2 palavras)
        partes_nome = nome.split() # Divide pelos espaços
        if len(partes_nome) < 2:
            return 'AGUARDANDO_NOME', {'tipo': 'texto', 'conteudo': "⚠️ Por favor, digite seu **Nome Completo** (Nome e Sobrenome). Tente novamente:"}

        # 3. Salva no banco
        sucesso = self.db.execute_write("UPDATE PARCEIROS_PERFIL SET NomeCompleto=? WHERE WhatsAppID=?", (nome, sender_id))
        
        if not sucesso:
             return 'AGUARDANDO_NOME', {'tipo': 'texto', 'conteudo': "⚠️ Erro ao salvar Nome. Tente novamente."}

        return 'AGUARDANDO_CEP', {'tipo': 'texto', 'conteudo': "📝 Dados pessoais salvos!\n\nAgora vamos para o endereço. Digite seu *CEP*:"}