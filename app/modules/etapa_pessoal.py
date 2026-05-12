from app.modules.common import GeradorResposta
from app.core.database import DatabaseManager
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
import re
import random
from app.core.config import Settings

logger = get_logger(__name__)


class EtapaPessoal:
    def __init__(self):
        self.db = DatabaseManager()

    def reenviar_etapa_atual(self, step_atual):
        if step_atual == 'AGUARDANDO_CNPJ':
            return step_atual, {'tipo': 'texto', 'conteudo': "Vamos retomar o cadastro.\n\nPor favor, digite o numero do seu *CNPJ* (apenas numeros):"}
        elif step_atual == 'AGUARDANDO_CPF':
            return step_atual, {'tipo': 'texto', 'conteudo': "Retomando validacao.\n\nPor favor, digite o seu *CPF* (apenas numeros):"}
        elif step_atual == 'AGUARDANDO_NOME':
            return step_atual, {'tipo': 'texto', 'conteudo': "Retomando.\n\nPor favor, digite seu *Nome Completo*:"}
        elif step_atual == 'AGUARDANDO_EMAIL':
            return step_atual, {'tipo': 'texto', 'conteudo': "Vamos continuar.\n\nPor favor, digite seu *E-mail* para contato:"}
        return None

    def processar_cnpj(self, texto, sender_id):
        cnpj_limpo = re.sub(r'[^a-zA-Z0-9]', '', texto).upper()

        if len(cnpj_limpo) != 14:
            msg_erro = f"*Formato incorreto!*\nO CNPJ deve ter 14 caracteres. Recebi {len(cnpj_limpo)}.\nEnvie novamente:"
            return 'AGUARDANDO_CNPJ', {'tipo': 'texto', 'conteudo': msg_erro}

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
            return 'AGUARDANDO_CNPJ', {'tipo': 'texto', 'conteudo': "Falha tecnica ao salvar CNPJ. Tente novamente."}

        settings = Settings()
        url_video = settings.get_secret('VIDEO-URL')

        lista_mensagens = [
            {'tipo': 'texto',
             'conteudo': f"Recebemos o CNPJ *{cnpj_limpo}*.\n\nEstamos consultando as bases governamentais para validacao.\nEnquanto aguarda, assista ao nosso video de apresentacao:",
             'delay': 1},
            {'tipo': 'media', 'url': url_video, 'legenda': "", 'delay': 1},
        ]

        chance = random.random()
        aprovado = chance < 0.99
        logger.info("validacao mock CNPJ",
                    extra={"custom_dimensions": {
                        ld.OPERATION: "validate_cnpj",
                        ld.RESULT: "approved" if aprovado else "rejected",
                        ld.MOCK: True,
                        ld.SENDER_HASH: mask_pii(sender_id),
                    }})

        if aprovado:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET StatusAtual='EM_ANALISE' WHERE WhatsAppID=?", (sender_id,))
            lista_mensagens.append({
                'tipo': 'texto',
                'conteudo': "*CNPJ Validado com Sucesso!*\n\nConsulta realizada e aprovada.\n\nAgora, digite seu *CPF* (apenas numeros) para prosseguir:",
                'delay': 30,
            })
            return 'AGUARDANDO_CPF', {'tipo': 'sequencia', 'mensagens': lista_mensagens}
        else:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET StatusAtual='CNPJ_REJEITADO' WHERE WhatsAppID=?", (sender_id,))
            lista_mensagens.append({
                'tipo': 'texto',
                'conteudo': "*Cadastro Nao Aprovado*\n\nInfelizmente identificamos pendencias cadastrais.\nAgradecemos seu interesse.",
                'delay': 30,
            })
            return 'FINALIZADO', {'tipo': 'sequencia', 'mensagens': lista_mensagens}

    def processar_cpf(self, texto, sender_id):
        cpf_limpo = re.sub(r'\D', '', texto)

        if len(cpf_limpo) != 11:
            msg_erro = f"*CPF Invalido!*\nO CPF deve ter 11 numeros. Recebi {len(cpf_limpo)}.\nPor favor, digite novamente:"
            return 'AGUARDANDO_CPF', {'tipo': 'texto', 'conteudo': msg_erro}

        sucesso = self.db.execute_write("UPDATE PARCEIROS_PERFIL SET CPF=? WHERE WhatsAppID=?", (cpf_limpo, sender_id))

        if not sucesso:
            return 'AGUARDANDO_CPF', {'tipo': 'texto', 'conteudo': "Erro tecnico ao salvar CPF. Tente novamente."}

        lista_mensagens = [
            {'tipo': 'texto', 'conteudo': f"Validando o CPF *{cpf_limpo}* na Receita Federal...", 'delay': 2}
        ]

        chance = random.random()
        aprovado = chance < 0.99
        logger.info("validacao mock CPF",
                    extra={"custom_dimensions": {
                        ld.OPERATION: "validate_cpf",
                        ld.RESULT: "approved" if aprovado else "rejected",
                        ld.MOCK: True,
                        ld.SENDER_HASH: mask_pii(sender_id),
                    }})

        if aprovado:
            lista_mensagens.append({
                'tipo': 'texto',
                'conteudo': "*CPF Aprovado!*\n\nAgora digite seu *Nome Completo*:",
                'delay': 5,
            })
            return 'AGUARDANDO_NOME', {'tipo': 'sequencia', 'mensagens': lista_mensagens}
        else:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET StatusAtual='CPF_REJEITADO' WHERE WhatsAppID=?", (sender_id,))
            lista_mensagens.append({
                'tipo': 'texto',
                'conteudo': "*CPF Nao Aprovado*\n\nIdentificamos restricoes neste CPF que impedem o prosseguimento do cadastro.\nAgradecemos o interesse.",
                'delay': 2,
            })
            return 'FINALIZADO', {'tipo': 'sequencia', 'mensagens': lista_mensagens}

    def processar_nome(self, texto, sender_id):
        nome = texto.strip()

        if len(nome) < 3:
            return 'AGUARDANDO_NOME', {'tipo': 'texto', 'conteudo': "Nome muito curto. Digite seu nome completo:"}

        partes_nome = nome.split()
        if len(partes_nome) < 2:
            return 'AGUARDANDO_NOME', {'tipo': 'texto', 'conteudo': "Por favor, digite seu **Nome Completo** (Nome e Sobrenome). Tente novamente:"}

        sucesso = self.db.execute_write("UPDATE PARCEIROS_PERFIL SET NomeCompleto=? WHERE WhatsAppID=?", (nome, sender_id))

        if not sucesso:
            return 'AGUARDANDO_NOME', {'tipo': 'texto', 'conteudo': "Erro ao salvar Nome. Tente novamente."}

        return 'AGUARDANDO_EMAIL', {'tipo': 'texto', 'conteudo': "Nome salvo!\n\nAgora, por favor, digite seu *E-mail* para contato:"}

    def processar_email(self, texto, sender_id):
        email = texto.strip().lower()

        regex_email = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        if not re.match(regex_email, email):
            return 'AGUARDANDO_EMAIL', {'tipo': 'texto', 'conteudo': "*E-mail invalido!*\n\nPor favor, digite um endereco de e-mail valido (ex: nome@gmail.com):"}

        sucesso = self.db.execute_write("UPDATE PARCEIROS_PERFIL SET Email=? WHERE WhatsAppID=?", (email, sender_id))

        if not sucesso:
            return 'AGUARDANDO_EMAIL', {'tipo': 'texto', 'conteudo': "Erro tecnico ao salvar o E-mail. Tente novamente."}

        return 'AGUARDANDO_CEP', {'tipo': 'texto', 'conteudo': "E-mail cadastrado!\n\nAgora vamos para o endereco. Digite seu *CEP*:"}
