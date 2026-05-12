import json

from app.core.database import DatabaseManager
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
from app.modules.onboarding import ModuloOnboarding
from app.modules.etapa_pessoal import EtapaPessoal
from app.modules.etapa_endereco import EtapaEndereco
from app.modules.etapa_habilidades import EtapaHabilidades
from app.modules.etapa_veiculos import EtapaVeiculos
from app.modules.etapa_disponibilidade import EtapaDisponibilidade
from app.modules.etapa_documentos import EtapaDocumentos
from app.modules.etapa_oferta import EtapaOferta

logger = get_logger(__name__)


class BotEngine:
    def __init__(self):
        self.db = DatabaseManager()

        self.onboarding = ModuloOnboarding()
        self.pessoal = EtapaPessoal()
        self.endereco = EtapaEndereco()
        self.habilidades = EtapaHabilidades()
        self.veiculos = EtapaVeiculos()
        self.disponibilidade = EtapaDisponibilidade()
        self.documentos = EtapaDocumentos()
        self.oferta = EtapaOferta()

        # MAPA DE RETOMADA (Fallback para texto simples)
        self.MAPA_RETOMADA = {
            'AGUARDANDO_CNPJ': "Otimo! Para iniciar, digite o numero do seu *CNPJ* (apenas numeros):",
            'AGUARDANDO_CPF': "CNPJ Validado! Digite o seu *CPF*:",
            'AGUARDANDO_NOME': "Perfeito. Agora digite seu *Nome Completo*:",
            'AGUARDANDO_EMAIL': "Certo. Digite seu *E-mail* para contato:",
            'AGUARDANDO_CEP': "Vamos para o endereco. Digite seu *CEP*:",
            'AGUARDANDO_BAIRRO': "Retomando: Qual e o seu *Bairro*?",
            'AGUARDANDO_RUA': "Retomando: Qual e o nome da *Rua*?",
            'AGUARDANDO_NUMERO': "Retomando: Digite o *Numero* da casa:",
            'AGUARDANDO_DISTANCIA': "Retomando: Qual a distancia maxima em KM que voce atende?",
            'INICIAR_HABILIDADES': "Endereco salvo! Vamos falar sobre servicos. Digite *OK*.",
            'INICIAR_VEICULOS': "Habilidades salvas! Vamos falar sobre Veiculos. Digite *OK*.",
            'AGUARDANDO_VEICULO_CARRO': "Retomando: Voce possui *Carro*? (Sim/Nao)",
            'AGUARDANDO_VEICULO_MOTO': "Retomando: Voce possui *Moto*? (Sim/Nao)",
            'INICIAR_DISPONIBILIDADE': "Veiculos salvos! Vamos configurar sua Agenda. Digite *OK*.",
            'AGUARDANDO_DISPONIBILIDADE_SEMANA': "Retomando: Qual sua disponibilidade durante a *Semana*?",
            'AGUARDANDO_DISPONIBILIDADE_FDS': "Retomando: Qual sua disponibilidade no *Final de Semana*?",
            'AGUARDANDO_DISPONIBILIDADE_FERIADO': "Retomando: Qual sua disponibilidade em *Feriados*?",
            'INICIAR_DOCUMENTOS': "Agenda salva! Vamos para os Documentos. Digite *OK*.",
            'AGUARDANDO_TIPO_DOC': "Retomando: Qual documento voce quer enviar? (CNH ou Identidade)",
            'AGUARDANDO_FRENTE_CNH': "Retomando: Envie a foto da *Frente da CNH*:",
            'AGUARDANDO_VERSO_CNH': "Retomando: Envie a foto do *Verso da CNH*:",
            'AGUARDANDO_FRENTE_RG': "Retomando: Envie a foto da *Frente do RG*:",
            'AGUARDANDO_VERSO_RG': "Retomando: Envie a foto do *Verso do RG*:",
            'AGUARDANDO_SELFIE': "Retomando: Envie sua *Selfie* com o documento:",
            'AGUARDANDO_PIX': "Retomando: Digite sua chave *PIX*:",
            'AGUARDANDO_TERMOS': "Retomando: Voce aceita os Termos? (Sim/Nao)",
        }

        for i in range(1, 10):
            self.MAPA_RETOMADA[f'AGUARDANDO_HABILIDADE_{i}'] = f"Retomando: Voce realiza o servico {i}? (Sim/Nao)"

        self.SAUDACOES = ['OI', 'OLA', 'EAI', 'BOM DIA', 'BOA TARDE', 'BOA NOITE', 'MENU', 'AJUDA', 'INICIO', 'RECOMECAR']

    def _get_session(self, sender_id):
        clean_id = sender_id.split('_')[0]
        sql = "SELECT CurrentStep, TempData, DATEDIFF(SECOND, LastUpdate, GETDATE()) FROM CHAT_SESSIONS WHERE WhatsAppID=?"
        row = self.db.execute_read_one(sql, (clean_id,))
        if row:
            step, dados_str, inativo = row
            dados = json.loads(dados_str) if dados_str else {}
            # Timeout 5 min
            if inativo is not None and inativo > 300:
                passos_ignorar = ['START', 'DECISAO_CONTINUAR', 'DECISAO_REFAZER', 'FINALIZADO', 'CHECK_DEVICE_RESPOSTA']
                if step not in passos_ignorar:
                    dados['step_backup'] = step
                return 'START', dados
            return step, dados
        return 'START', {}

    def _save_session(self, sender_id, step, dados):
        clean_id = sender_id.split('_')[0]

        if step in ['START', 'NO_UPDATE']:
            return

        dados_str = json.dumps(dados)
        sql = """
        MERGE CHAT_SESSIONS AS target
        USING (SELECT ? AS WhatsAppID) AS source
        ON (target.WhatsAppID = source.WhatsAppID)
        WHEN MATCHED THEN
            UPDATE SET CurrentStep = ?, TempData = ?, LastUpdate = GETDATE()
        WHEN NOT MATCHED THEN
            INSERT (WhatsAppID, CurrentStep, TempData, LastUpdate)
            VALUES (?, ?, ?, GETDATE());
        """
        self.db.execute_write(sql, (clean_id, step, dados_str, clean_id, step, dados_str))

    def processar_mensagem(self, sender_id, mensagem_texto, media_url=None):
        try:
            clean_id = sender_id.split('_')[0]
            texto_clean = mensagem_texto.strip().upper() if mensagem_texto else ""

            dados_oferta = self.oferta.verificar_oferta_pendente(clean_id)

            if dados_oferta:
                logger.info("interceptando fluxo para oferta pendente",
                            extra={"custom_dimensions": {
                                ld.OPERATION: "oferta_intercept",
                                ld.SENDER_HASH: mask_pii(clean_id),
                            }})
                step_dummy, resposta = self.oferta.processar_resposta(mensagem_texto, dados_oferta, clean_id)
                return resposta

            step_atual, dados = self._get_session(clean_id)
            novo_step = step_atual
            resposta = {}

            logger.info("processando mensagem",
                        extra={"custom_dimensions": {
                            ld.OPERATION: "process_message",
                            ld.SENDER_HASH: mask_pii(clean_id),
                            ld.STEP: step_atual,
                            ld.MESSAGE_LEN: len(mensagem_texto or ""),
                        }})

            # 1. SAUDACAO (Backup e Menu)
            if texto_clean in self.SAUDACOES and step_atual not in ['START', 'FINALIZADO', 'DECISAO_REFAZER', 'CHECK_DEVICE_RESPOSTA']:
                if step_atual != 'DECISAO_CONTINUAR':
                    dados['step_backup'] = step_atual
                novo_step, resposta = self.onboarding.processar_inicio(clean_id)
                self._save_session(clean_id, novo_step, dados)
                return resposta

            # 2. ROTEAMENTO
            if step_atual == 'START':
                novo_step, resposta = self.onboarding.processar_inicio(clean_id)

            elif step_atual == 'DECISAO_REFAZER':
                novo_step, resposta = self.onboarding.processar_decisao_refazer(mensagem_texto, clean_id)

            elif step_atual == 'DECISAO_CONTINUAR':
                retorno = self.onboarding.processar_decisao_continuar(mensagem_texto, clean_id)
                if isinstance(retorno, tuple):
                    sinal, resp_obj = retorno
                else:
                    sinal = retorno
                    resp_obj = {}

                # LOGICA CENTRAL DE RETOMADA INTELIGENTE
                if sinal == 'RETOMAR_FLUXO':
                    step_backup = dados.get('step_backup', 'AGUARDANDO_CNPJ')

                    # 1. VEICULOS
                    if 'VEICULO' in step_backup and step_backup != 'INICIAR_VEICULOS':
                        logger.debug("retomando veiculo especifico",
                                     extra={"custom_dimensions": {ld.OPERATION: "resume", "step_backup": step_backup}})
                        if hasattr(self.veiculos, 'reenviar_etapa_atual'):
                            res_veiculo = self.veiculos.reenviar_etapa_atual(step_backup)
                            if res_veiculo:
                                novo_step, resposta = res_veiculo
                            else:
                                novo_step, resposta = self.veiculos.iniciar_modulo(clean_id)
                        else:
                            novo_step, resposta = self.veiculos.iniciar_modulo(clean_id)

                    elif step_backup == 'INICIAR_VEICULOS':
                        novo_step, resposta = self.veiculos.iniciar_modulo(clean_id)

                    # 2. DISPONIBILIDADE
                    elif 'DISPONIBILIDADE' in step_backup:
                        logger.debug("retomando disponibilidade",
                                     extra={"custom_dimensions": {ld.OPERATION: "resume", "step_backup": step_backup}})
                        if step_backup != 'INICIAR_DISPONIBILIDADE' and hasattr(self.disponibilidade, 'reenviar_etapa_atual'):
                            res_disp = self.disponibilidade.reenviar_etapa_atual(step_backup)
                            if res_disp:
                                novo_step, resposta = res_disp
                            else:
                                novo_step, resposta = self.disponibilidade.iniciar_modulo(clean_id)
                        else:
                            novo_step, resposta = self.disponibilidade.iniciar_modulo(clean_id)

                    # 3. HABILIDADES
                    elif 'HABILIDADE' in step_backup and step_backup != 'INICIAR_HABILIDADES':
                        logger.debug("retomando habilidade",
                                     extra={"custom_dimensions": {ld.OPERATION: "resume", "step_backup": step_backup}})
                        res_hab = self.habilidades.reenviar_etapa_atual(step_backup)
                        if res_hab:
                            novo_step, resposta = res_hab
                        else:
                            msg = self.MAPA_RETOMADA.get(step_backup, "Vamos retomar.")
                            novo_step, resposta = step_backup, {'tipo': 'texto', 'conteudo': msg}

                    # 4. DADOS PESSOAIS
                    elif step_backup in ['AGUARDANDO_CNPJ', 'AGUARDANDO_CPF', 'AGUARDANDO_NOME', 'AGUARDANDO_EMAIL']:
                        logger.debug("retomando dados pessoais",
                                     extra={"custom_dimensions": {ld.OPERATION: "resume", "step_backup": step_backup}})
                        res_pessoal = self.pessoal.reenviar_etapa_atual(step_backup)
                        if res_pessoal:
                            novo_step, resposta = res_pessoal
                        else:
                            msg = self.MAPA_RETOMADA.get(step_backup, "Vamos retomar.")
                            novo_step, resposta = step_backup, {'tipo': 'texto', 'conteudo': msg}

                    # 5. DOCUMENTOS
                    elif step_backup == 'INICIAR_DOCUMENTOS' or step_backup.startswith('AGUARDANDO_') and (
                        'DOC' in step_backup or 'FRENTE' in step_backup or 'VERSO' in step_backup
                        or 'SELFIE' in step_backup or 'PIX' in step_backup or 'TERMOS' in step_backup
                    ):
                        logger.debug("retomando documentos",
                                     extra={"custom_dimensions": {ld.OPERATION: "resume", "step_backup": step_backup}})
                        res_docs = self.documentos.reenviar_etapa_atual(step_backup)
                        if res_docs:
                            novo_step, resposta = res_docs
                        else:
                            msg = self.MAPA_RETOMADA.get(step_backup, "Vamos retomar.")
                            novo_step, resposta = step_backup, {'tipo': 'texto', 'conteudo': msg}

                    # 6. Fallback final
                    else:
                        msg_texto = self.MAPA_RETOMADA.get(step_backup, "Vamos retomar.")
                        novo_step = step_backup
                        resposta = {'tipo': 'texto', 'conteudo': msg_texto}

                elif sinal == 'DECISAO_REFAZER':
                    novo_step = 'DECISAO_REFAZER'
                    resposta = resp_obj
                elif sinal == 'PAUSAR_FLUXO':
                    novo_step = dados.get('step_backup') or 'START'
                    resposta = resp_obj
                else:
                    novo_step = sinal
                    resposta = resp_obj

            # --- DADOS PESSOAIS ---
            elif step_atual == 'CHECK_DEVICE_RESPOSTA':
                novo_step, resposta = self.onboarding.processar_check_device(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_CNPJ':
                novo_step, resposta = self.pessoal.processar_cnpj(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_CPF':
                novo_step, resposta = self.pessoal.processar_cpf(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_NOME':
                novo_step, resposta = self.pessoal.processar_nome(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_EMAIL':
                novo_step, resposta = self.pessoal.processar_email(mensagem_texto, clean_id)

            # --- ENDERECO ---
            elif step_atual == 'AGUARDANDO_CEP':
                novo_step, resposta = self.endereco.processar_cep(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_BAIRRO':
                novo_step, resposta = self.endereco.processar_bairro(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_RUA':
                novo_step, resposta = self.endereco.processar_rua(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_NUMERO':
                novo_step, resposta = self.endereco.processar_numero(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_DISTANCIA':
                novo_step, resposta = self.endereco.processar_distancia(mensagem_texto, clean_id)

            # --- HABILIDADES ---
            elif step_atual == 'INICIAR_HABILIDADES':
                novo_step, resposta = self.habilidades.iniciar_modulo(clean_id)
            elif step_atual.startswith('AGUARDANDO_HABILIDADE_'):
                novo_step, resposta = self.habilidades.processar_resposta(step_atual, mensagem_texto, clean_id)

            # --- VEICULOS ---
            elif step_atual == 'INICIAR_VEICULOS':
                novo_step, resposta = self.veiculos.iniciar_modulo(clean_id)
            elif step_atual == 'AGUARDANDO_VEICULO_CARRO':
                novo_step, resposta = self.veiculos.processar_carro(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_VEICULO_MOTO':
                novo_step, resposta = self.veiculos.processar_moto(mensagem_texto, clean_id)

            # --- DISPONIBILIDADE ---
            elif step_atual == 'INICIAR_DISPONIBILIDADE':
                novo_step, resposta = self.disponibilidade.iniciar_modulo(clean_id)
            elif step_atual.startswith('AGUARDANDO_DISPONIBILIDADE_'):
                novo_step, resposta = self.disponibilidade.processar_resposta(step_atual, mensagem_texto, clean_id)

            # --- DOCUMENTOS ---
            elif step_atual == 'INICIAR_DOCUMENTOS' or step_atual.startswith('AGUARDANDO_') and (
                'DOC' in step_atual or 'FRENTE' in step_atual or 'VERSO' in step_atual
                or 'SELFIE' in step_atual or 'PIX' in step_atual or 'TERMOS' in step_atual
            ):
                if step_atual == 'INICIAR_DOCUMENTOS':
                    novo_step, resposta = self.documentos.iniciar_modulo(clean_id)
                else:
                    novo_step, resposta = self.documentos.processar_resposta(step_atual, mensagem_texto, media_url, clean_id)

            # --- FIM ---
            elif step_atual in ['FINALIZADO', 'FINALIZADO_SEM_ACEITE']:
                novo_step, resposta = self.onboarding.processar_inicio(clean_id)
            else:
                resposta = self.onboarding.processar_inicio(clean_id)
                novo_step = 'START'

            # 3. SALVA SESSAO
            if novo_step != step_atual or step_atual == 'START':
                self._save_session(clean_id, novo_step, dados)

            return resposta

        except Exception:
            logger.error("erro no bot engine", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "process_message",
                             ld.SENDER_HASH: mask_pii(sender_id),
                         }})
            return {'tipo': 'texto', 'conteudo': "Ocorreu um erro interno. Tente novamente."}
