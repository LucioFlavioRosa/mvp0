import json
import traceback
from app.core.database import DatabaseManager
from app.modules.common import GeradorResposta
from app.modules.onboarding import ModuloOnboarding
from app.modules.etapa_pessoal import EtapaPessoal
from app.modules.etapa_endereco import EtapaEndereco
from app.modules.etapa_habilidades import EtapaHabilidades
from app.modules.etapa_veiculos import EtapaVeiculos
from app.modules.etapa_disponibilidade import EtapaDisponibilidade
from app.modules.etapa_documentos import EtapaDocumentos 

class BotEngine:
    def __init__(self):
        self.db = DatabaseManager()
        
        # Inicialização dos Módulos
        self.onboarding = ModuloOnboarding()
        self.pessoal = EtapaPessoal()
        self.endereco = EtapaEndereco()
        self.habilidades = EtapaHabilidades()
        self.veiculos = EtapaVeiculos()
        self.disponibilidade = EtapaDisponibilidade()
        self.documentos = EtapaDocumentos()
        
        # MAPA DE RETOMADA (Fallback para texto simples)
        self.MAPA_RETOMADA = {
            'AGUARDANDO_CNPJ': "✅ Ótimo! Para iniciar, digite o número do seu *CNPJ* (apenas números):",
            'AGUARDANDO_CPF': "✅ CNPJ Validado! Digite o seu *CPF*:",
            'AGUARDANDO_NOME': "✅ Perfeito. Agora digite seu *Nome Completo*:",
            'AGUARDANDO_CEP': "📝 Vamos para o endereço. Digite seu *CEP*:",
            'AGUARDANDO_BAIRRO': "Retomando: Qual é o seu *Bairro*?",
            'AGUARDANDO_RUA': "Retomando: Qual é o nome da *Rua*?",
            'AGUARDANDO_NUMERO': "Retomando: Digite o *Número* da casa:",
            'AGUARDANDO_DISTANCIA': "Retomando: Qual a distância máxima em KM que você atende?",
            'INICIAR_HABILIDADES': "✅ Endereço salvo! Vamos falar sobre serviços. Digite *OK*.",
            'INICIAR_VEICULOS': "🛠️ Habilidades salvas! Vamos falar sobre Veículos. Digite *OK*.",
            'AGUARDANDO_VEICULO_CARRO': "Retomando: Você possui *Carro*? (Sim/Não)",
            'AGUARDANDO_VEICULO_MOTO': "Retomando: Você possui *Moto*? (Sim/Não)",
            'INICIAR_DISPONIBILIDADE': "🚗 Veículos salvos! Vamos configurar sua Agenda. Digite *OK*.",
            'AGUARDANDO_DISPONIBILIDADE_SEMANA': "Retomando: Qual sua disponibilidade durante a *Semana*?",
            'AGUARDANDO_DISPONIBILIDADE_FDS': "Retomando: Qual sua disponibilidade no *Final de Semana*?",
            'AGUARDANDO_DISPONIBILIDADE_FERIADO': "Retomando: Qual sua disponibilidade em *Feriados*?",
            'INICIAR_DOCUMENTOS': "🗓️ Agenda salva! Vamos para os Documentos. Digite *OK*.",
            'AGUARDANDO_TIPO_DOC': "Retomando: Qual documento você quer enviar? (CNH ou Identidade)",
            'AGUARDANDO_FRENTE_CNH': "Retomando: Envie a foto da *Frente da CNH*:",
            'AGUARDANDO_VERSO_CNH': "Retomando: Envie a foto do *Verso da CNH*:",
            'AGUARDANDO_FRENTE_RG': "Retomando: Envie a foto da *Frente do RG*:",
            'AGUARDANDO_VERSO_RG': "Retomando: Envie a foto do *Verso do RG*:",
            'AGUARDANDO_SELFIE': "Retomando: Envie sua *Selfie* com o documento:",
            'AGUARDANDO_PIX': "Retomando: Digite sua chave *PIX*:",
            'AGUARDANDO_TERMOS': "Retomando: Você aceita os Termos? (Sim/Não)"
        }
        
        for i in range(1, 10): self.MAPA_RETOMADA[f'AGUARDANDO_HABILIDADE_{i}'] = f"Retomando: Você realiza o serviço {i}? (Sim/Não)"
        self.SAUDACOES = ['OI', 'OLA', 'OLÁ', 'EAI', 'BOM DIA', 'BOA TARDE', 'BOA NOITE', 'MENU', 'AJUDA', 'INICIO', 'RECOMEÇAR']

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

        # Bloqueio de salvamento de passos transitórios (Previne loop)
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
            step_atual, dados = self._get_session(clean_id)
            texto_clean = mensagem_texto.strip().upper() if mensagem_texto else ""
            novo_step = step_atual
            resposta = {}

            print(f"🤖 Step: {step_atual} | Msg: {mensagem_texto}")

            # 1. SAUDAÇÃO (Backup e Menu)
            if texto_clean in self.SAUDACOES and step_atual not in ['START', 'FINALIZADO', 'DECISAO_REFAZER', 'CHECK_DEVICE_RESPOSTA']:
                if step_atual != 'DECISAO_CONTINUAR': dados['step_backup'] = step_atual
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
                if isinstance(retorno, tuple): sinal, resp_obj = retorno
                else: sinal = retorno; resp_obj = {}

                # ==========================================================
                # 🟢 LÓGICA CENTRAL DE RETOMADA INTELIGENTE
                # ==========================================================
                if sinal == 'RETOMAR_FLUXO':
                    step_backup = dados.get('step_backup', 'AGUARDANDO_CNPJ')
                    
                    # 1. VEÍCULOS
                    if 'VEICULO' in step_backup and step_backup != 'INICIAR_VEICULOS':
                        print("DEBUG: Retomando Veículo Específico")
                        if hasattr(self.veiculos, 'reenviar_etapa_atual'):
                            res_veiculo = self.veiculos.reenviar_etapa_atual(step_backup)
                            if res_veiculo: novo_step, resposta = res_veiculo
                            else: novo_step, resposta = self.veiculos.iniciar_modulo(clean_id)
                        else:
                            novo_step, resposta = self.veiculos.iniciar_modulo(clean_id)
                    
                    elif step_backup == 'INICIAR_VEICULOS':
                         novo_step, resposta = self.veiculos.iniciar_modulo(clean_id)

                    # 2. DISPONIBILIDADE
                    elif 'DISPONIBILIDADE' in step_backup:
                        print(f"DEBUG: Retomando Disponibilidade: {step_backup}")
                        if step_backup != 'INICIAR_DISPONIBILIDADE' and hasattr(self.disponibilidade, 'reenviar_etapa_atual'):
                            res_disp = self.disponibilidade.reenviar_etapa_atual(step_backup)
                            if res_disp: novo_step, resposta = res_disp
                            else: novo_step, resposta = self.disponibilidade.iniciar_modulo(clean_id)
                        else:
                            novo_step, resposta = self.disponibilidade.iniciar_modulo(clean_id)
                    
                    # 3. HABILIDADES
                    elif 'HABILIDADE' in step_backup and step_backup != 'INICIAR_HABILIDADES':
                        print(f"DEBUG: Retomando Habilidade: {step_backup}")
                        res_hab = self.habilidades.reenviar_etapa_atual(step_backup)
                        if res_hab: novo_step, resposta = res_hab
                        else: 
                            msg = self.MAPA_RETOMADA.get(step_backup, "Vamos retomar.")
                            novo_step, resposta = step_backup, {'tipo': 'texto', 'conteudo': msg}

                    # 4. DADOS PESSOAIS
                    elif step_backup in ['AGUARDANDO_CNPJ', 'AGUARDANDO_CPF', 'AGUARDANDO_NOME']:
                        print(f"DEBUG: Retomando Pessoal: {step_backup}")
                        res_pessoal = self.pessoal.reenviar_etapa_atual(step_backup)
                        if res_pessoal:
                             novo_step, resposta = res_pessoal
                        else:
                             msg = self.MAPA_RETOMADA.get(step_backup, "Vamos retomar.")
                             novo_step, resposta = step_backup, {'tipo': 'texto', 'conteudo': msg}

                    # 5. DOCUMENTOS
                    elif step_backup == 'INICIAR_DOCUMENTOS' or step_backup.startswith('AGUARDANDO_') and ('DOC' in step_backup or 'FRENTE' in step_backup or 'VERSO' in step_backup or 'SELFIE' in step_backup or 'PIX' in step_backup or 'TERMOS' in step_backup):
                        print(f"DEBUG: Retomando Documentos: {step_backup}")
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
            elif step_atual == 'CHECK_DEVICE_RESPOSTA': novo_step, resposta = self.onboarding.processar_check_device(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_CNPJ': novo_step, resposta = self.pessoal.processar_cnpj(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_CPF': novo_step, resposta = self.pessoal.processar_cpf(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_NOME': novo_step, resposta = self.pessoal.processar_nome(mensagem_texto, clean_id)
            
            # --- ENDEREÇO ---
            elif step_atual == 'AGUARDANDO_CEP': novo_step, resposta = self.endereco.processar_cep(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_BAIRRO': novo_step, resposta = self.endereco.processar_bairro(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_RUA': novo_step, resposta = self.endereco.processar_rua(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_NUMERO': novo_step, resposta = self.endereco.processar_numero(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_DISTANCIA': novo_step, resposta = self.endereco.processar_distancia(mensagem_texto, clean_id)
            
            # --- HABILIDADES ---
            elif step_atual == 'INICIAR_HABILIDADES': novo_step, resposta = self.habilidades.iniciar_modulo(clean_id)
            
            # 🔴 CORREÇÃO: Chamada direta e simples, sem validação complexa
            elif step_atual.startswith('AGUARDANDO_HABILIDADE_'):
                novo_step, resposta = self.habilidades.processar_resposta(step_atual, mensagem_texto, clean_id)

            # --- VEÍCULOS ---
            elif step_atual == 'INICIAR_VEICULOS': novo_step, resposta = self.veiculos.iniciar_modulo(clean_id)
            elif step_atual == 'AGUARDANDO_VEICULO_CARRO': novo_step, resposta = self.veiculos.processar_carro(mensagem_texto, clean_id)
            elif step_atual == 'AGUARDANDO_VEICULO_MOTO': novo_step, resposta = self.veiculos.processar_moto(mensagem_texto, clean_id)

            # --- DISPONIBILIDADE ---
            elif step_atual == 'INICIAR_DISPONIBILIDADE': novo_step, resposta = self.disponibilidade.iniciar_modulo(clean_id)
            elif step_atual.startswith('AGUARDANDO_DISPONIBILIDADE_'): novo_step, resposta = self.disponibilidade.processar_resposta(step_atual, mensagem_texto, clean_id)

            # --- DOCUMENTOS ---
            elif step_atual == 'INICIAR_DOCUMENTOS' or step_atual.startswith('AGUARDANDO_') and ('DOC' in step_atual or 'FRENTE' in step_atual or 'VERSO' in step_atual or 'SELFIE' in step_atual or 'PIX' in step_atual or 'TERMOS' in step_atual):
                if step_atual == 'INICIAR_DOCUMENTOS': novo_step, resposta = self.documentos.iniciar_modulo(clean_id)
                else: novo_step, resposta = self.documentos.processar_resposta(step_atual, mensagem_texto, media_url, clean_id)

            # --- FIM ---
            elif step_atual in ['FINALIZADO', 'FINALIZADO_SEM_ACEITE']: 
                novo_step, resposta = self.onboarding.processar_inicio(clean_id)
            else:
                resposta = self.onboarding.processar_inicio(clean_id)
                novo_step = 'START'

            # 3. SALVA SESSÃO
            if novo_step != step_atual or step_atual == 'START':
                self._save_session(clean_id, novo_step, dados)
            
            return resposta

        except Exception as e:
            print(f"🔥 ERRO NO BOT: {e}")
            traceback.print_exc()
            return {'tipo': 'texto', 'conteudo': "⚠️ Ocorreu um erro interno. Tente novamente."}