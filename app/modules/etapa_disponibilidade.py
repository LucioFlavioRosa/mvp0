from app.core.database import DatabaseManager
import threading 

class EtapaDisponibilidade:
    def __init__(self):
        self.db = DatabaseManager()
        
        # ID do Template de Documentos (Transição final)
        self.TEMPLATE_DOCS = "HX725fe0933cb5a8ab346c2afe1e05471f"

        # ⚠️ IMPORTANTE: Templates de PERGUNTA SIM/NÃO
        self.TEMPLATE_SEMANA  = "HXbe40fbb6741a733ebc2182ede584cc05"
        self.TEMPLATE_FDS     = "HX00cba18d4685201ea44127e8edb0ec4d"
        self.TEMPLATE_FERIADO = "HX72cee6cb331141891b6fffce8bfe2f17"

        # CONFIGURAÇÃO DOS BLOCOS
        self.ETAPAS = {
            'SEMANA': {
                'nome': 'Meio de Semana',
                'template_sid': self.TEMPLATE_SEMANA,
                'id_db': 1, # 1 = Durante a Semana
                'proximo': 'AGUARDANDO_DISPONIBILIDADE_FDS'
            },
            'FDS': {
                'nome': 'Final de Semana',
                'template_sid': self.TEMPLATE_FDS,
                'id_db': 2, # 2 = Final de Semana
                'proximo': 'AGUARDANDO_DISPONIBILIDADE_FERIADO'
            },
            'FERIADO': {
                'nome': 'Feriados',
                'template_sid': self.TEMPLATE_FERIADO,
                'id_db': 3, # 3 = Feriado
                'proximo': 'INICIAR_DOCUMENTOS'
            }
        }

    def _enviar_bloco(self, etapa_key):
        """Gera o template da etapa atual"""
        config = self.ETAPAS[etapa_key]
        return f'AGUARDANDO_DISPONIBILIDADE_{etapa_key}', {
            'tipo': 'template',
            'sid': config['template_sid'],
            'variaveis': {}
        }

    # 🟢 NOVO MÉTODO: Retomada Inteligente
    def reenviar_etapa_atual(self, step_atual):
        # 1. Identifica qual etapa é baseada no nome do passo
        # Ex: AGUARDANDO_DISPONIBILIDADE_FDS -> 'FDS'
        try:
            etapa_key = step_atual.split('_')[-1]
            config = self.ETAPAS.get(etapa_key)
            
            if config:
                return self._enviar_bloco(etapa_key)
        except:
            pass
            
        return None

    def _salvar_disponibilidade(self, tipo_dia, periodo_id, sender_id):
        """
        Salva o registro simplificado.
        """
        try:
            sql = """
            INSERT INTO PARCEIROS_DISPONIBILIDADE (DisponibilidadeID, ParceiroUUID, DiaSemana, Periodo, Ativo)
            SELECT NEWID(), P.ParceiroUUID, ?, ?, 1
            FROM PARCEIROS_PERFIL P
            WHERE P.WhatsAppID = ?
            AND NOT EXISTS (
                SELECT 1 FROM PARCEIROS_DISPONIBILIDADE PD 
                WHERE PD.ParceiroUUID = P.ParceiroUUID 
                AND PD.DiaSemana = ? 
            )
            """
            self.db.execute_write(sql, (tipo_dia, periodo_id, sender_id, tipo_dia))
            
            print(f"✅ [Background] Disponibilidade Tipo {tipo_dia} (Periodo {periodo_id}) salva.")
            
        except Exception as e:
            print(f"🔥 [Background Erro] Falha ao salvar disponibilidade: {e}")

    def iniciar_modulo(self, sender_id):
        return self._enviar_bloco('SEMANA')

    def processar_resposta(self, step_atual, texto, sender_id):
        # 1. Identifica qual bloco estamos
        try:
            etapa_key = step_atual.split('_')[-1] # Ex: SEMANA
            config_etapa = self.ETAPAS.get(etapa_key)
        except:
            return step_atual, {'tipo': 'texto', 'conteudo': "Erro interno. Digite OK para reiniciar."}

        if not config_etapa:
            return self.iniciar_modulo(sender_id)

        # 2. Interpretação da Resposta (SIM ou NÃO)
        resp = texto.strip().upper()
        
        # Variável para definir se devemos salvar
        salvar_no_banco = False
        
        # Validação Simplificada
        if resp in ['SIM', 'S', 'YES', 'CLARO', 'QUERO']:
            salvar_no_banco = True
        elif resp in ['NAO', 'NÃO', 'N', 'NO', 'NUNCA']:
            salvar_no_banco = False
        else:
            # Se não entendeu, pede para usar os botões
            return step_atual, {'tipo': 'texto', 'conteudo': "⚠️ Resposta inválida. Por favor, responda com SIM ou NÃO."}

        # 3. Dispara Salvamento (Apenas se for SIM)
        if salvar_no_banco:
            id_tipo_dia = config_etapa['id_db'] # 1, 2 ou 3
            
            # Como não perguntamos o período, salvamos como '3' (Dia Todo / Disponível Geral)
            periodo_padrao = 3 
            
            thread_db = threading.Thread(
                target=self._salvar_disponibilidade,
                args=(id_tipo_dia, periodo_padrao, sender_id)
            )
            thread_db.start()
        else:
            print(f"ℹ️ [Info] Usuário respondeu NÃO para {config_etapa['nome']}. Nada será salvo.")

        # 4. Define o próximo passo
        proximo_step = config_etapa['proximo']

        # ======================================================================
        # 🟢 TRANSIÇÃO -> DOCUMENTOS
        # ======================================================================
        if proximo_step == 'INICIAR_DOCUMENTOS':
            return 'AGUARDANDO_TIPO_DOC', {
                'tipo': 'sequencia',
                'mensagens': [
                    {'tipo': 'texto', 'conteudo': "✅ Disponibilidade registrada!", 'delay': 1},
                    {'tipo': 'texto', 'conteudo': "📂 *Etapa Final: Documentos*\n\nAgora precisamos das fotos dos seus documentos.", 'delay': 2},
                    {
                        'tipo': 'template',
                        'sid': self.TEMPLATE_DOCS,
                        'variaveis': {},
                        'delay': 1
                    }
                ]
            }
        
        # Se tem próxima etapa (ex: FDS ou FERIADO)
        prox_etapa_key = proximo_step.split('_')[-1]
        return self._enviar_bloco(prox_etapa_key)