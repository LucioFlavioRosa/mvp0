from app.core.database import DatabaseManager
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
import threading

logger = get_logger(__name__)


class EtapaHabilidades:
    def __init__(self):
        self.db = DatabaseManager()

        self.TEMPLATE_VEICULOS = "HX92d60698b590fe47e24e166d65531eef"

        self.FLUXO = {
            '1': {'id_habilidade': 1, 'descricao': "Manutencao de Hidrometros", 'template_sid': 'HX24e1bcb7e514d6fca272f38691c76a33', 'proximo': 'AGUARDANDO_HABILIDADE_2'},
            '2': {'id_habilidade': 2, 'descricao': "Ligacoes de Agua e Esgoto", 'template_sid': 'HX72176f6bb644719b83ff4d283ea1d586', 'proximo': 'AGUARDANDO_HABILIDADE_3'},
            '3': {'id_habilidade': 3, 'descricao': "Combate a Fraudes", 'template_sid': 'HX6bdb1435da31742cca8cc7b1bbe3ce99', 'proximo': 'AGUARDANDO_HABILIDADE_4'},
            '4': {'id_habilidade': 4, 'descricao': "Verificacao de Consumo", 'template_sid': 'HXa4e41567c8dac4b573ac4d940df58249', 'proximo': 'AGUARDANDO_HABILIDADE_5'},
            '5': {'id_habilidade': 5, 'descricao': "Manutencao da Rede de Esgoto na Rua", 'template_sid': 'HXdba84c0e8c46f2de94464e4f2468c213', 'proximo': 'AGUARDANDO_HABILIDADE_7'},
            '7': {'id_habilidade': 7, 'descricao': "Operacao Rede Distribuicao", 'template_sid': 'HX080222a6097b808579c11838b278959d', 'proximo': 'AGUARDANDO_HABILIDADE_8'},
            '8': {'id_habilidade': 8, 'descricao': "Cadastro", 'template_sid': 'HX4ec2c189146a69807ee842bac9f056de', 'proximo': 'INICIAR_VEICULOS'},
        }

    def _gerar_resposta_template(self, proximo_passo, template_sid):
        return proximo_passo, {'tipo': 'template', 'sid': template_sid, 'variaveis': {}}

    def reenviar_etapa_atual(self, step_atual):
        try:
            step_key = step_atual.split('_')[-1]
            config = self.FLUXO.get(step_key)
            if config:
                return self._gerar_resposta_template(step_atual, config['template_sid'])
        except Exception:
            pass
        return None

    def _salvar_background(self, id_habilidade, sender_id):
        try:
            sql = "INSERT INTO PARCEIROS_HABILIDADES (HabilidadeID, ParceiroUUID, TipoServicoID, TempoExperiencia) SELECT NEWID(), P.ParceiroUUID, ?, NULL FROM PARCEIROS_PERFIL P WHERE P.WhatsAppID = ? AND NOT EXISTS (SELECT 1 FROM PARCEIROS_HABILIDADES PH WHERE PH.ParceiroUUID = P.ParceiroUUID AND PH.TipoServicoID = ?)"
            self.db.execute_write(sql, (id_habilidade, sender_id, id_habilidade))
            logger.info("habilidade processada",
                        extra={"custom_dimensions": {
                            ld.OPERATION: "save_habilidade",
                            ld.SENDER_HASH: mask_pii(sender_id),
                            "id_habilidade": id_habilidade,
                        }})
        except Exception:
            logger.error("falha ao salvar habilidade", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "save_habilidade",
                             ld.SENDER_HASH: mask_pii(sender_id),
                             "id_habilidade": id_habilidade,
                         }})

    def iniciar_modulo(self, sender_id):
        config_q1 = self.FLUXO['1']
        return self._gerar_resposta_template('AGUARDANDO_HABILIDADE_1', config_q1['template_sid'])

    def processar_resposta(self, step_atual, texto, sender_id):
        try:
            step_key = step_atual.split('_')[-1]
            config_atual = self.FLUXO.get(step_key)
        except Exception:
            return step_atual, {'tipo': 'texto', 'conteudo': "Erro interno."}

        if not config_atual:
            return step_atual, {'tipo': 'texto', 'conteudo': "Configuracao nao encontrada."}

        resp_clean = texto.strip().upper()
        if resp_clean not in ['SIM', 'S', 'NAO', 'N']:
            return step_atual, {'tipo': 'texto', 'conteudo': "Resposta invalida. Use os botoes SIM ou NAO."}

        if resp_clean in ['SIM', 'S']:
            threading.Thread(target=self._salvar_background, args=(config_atual['id_habilidade'], sender_id)).start()

        proximo_step = config_atual['proximo']

        if proximo_step == 'INICIAR_VEICULOS':
            return 'AGUARDANDO_VEICULO_CARRO', {
                'tipo': 'sequencia',
                'mensagens': [
                    {'tipo': 'texto', 'conteudo': "Habilidades registradas!", 'delay': 1},
                    {'tipo': 'texto', 'conteudo': "*Nova Etapa: Veiculos*\n\nAgora vamos falar sobre seu transporte.", 'delay': 2},
                    {'tipo': 'template', 'sid': self.TEMPLATE_VEICULOS, 'variaveis': {}, 'delay': 1},
                ],
            }

        prox_key = proximo_step.split('_')[-1]
        return self._gerar_resposta_template(proximo_step, self.FLUXO[prox_key]['template_sid'])
