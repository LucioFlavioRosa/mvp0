from app.core.database import DatabaseManager
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
import threading

logger = get_logger(__name__)


class EtapaDisponibilidade:
    def __init__(self):
        self.db = DatabaseManager()

        self.TEMPLATE_DOCS = "HX725fe0933cb5a8ab346c2afe1e05471f"
        self.TEMPLATE_SEMANA = "HXbe40fbb6741a733ebc2182ede584cc05"
        self.TEMPLATE_FDS = "HX00cba18d4685201ea44127e8edb0ec4d"
        self.TEMPLATE_FERIADO = "HX72cee6cb331141891b6fffce8bfe2f17"

        self.ETAPAS = {
            'SEMANA': {
                'nome': 'Meio de Semana',
                'template_sid': self.TEMPLATE_SEMANA,
                'id_db': 1,
                'proximo': 'AGUARDANDO_DISPONIBILIDADE_FDS',
            },
            'FDS': {
                'nome': 'Final de Semana',
                'template_sid': self.TEMPLATE_FDS,
                'id_db': 2,
                'proximo': 'AGUARDANDO_DISPONIBILIDADE_FERIADO',
            },
            'FERIADO': {
                'nome': 'Feriados',
                'template_sid': self.TEMPLATE_FERIADO,
                'id_db': 3,
                'proximo': 'INICIAR_DOCUMENTOS',
            },
        }

    def _enviar_bloco(self, etapa_key):
        """Gera o template da etapa atual"""
        config = self.ETAPAS[etapa_key]
        return f'AGUARDANDO_DISPONIBILIDADE_{etapa_key}', {
            'tipo': 'template',
            'sid': config['template_sid'],
            'variaveis': {},
        }

    def reenviar_etapa_atual(self, step_atual):
        try:
            etapa_key = step_atual.split('_')[-1]
            config = self.ETAPAS.get(etapa_key)
            if config:
                return self._enviar_bloco(etapa_key)
        except Exception:
            pass
        return None

    def _salvar_disponibilidade(self, tipo_dia, periodo_id, sender_id):
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
            logger.info("disponibilidade salva",
                        extra={"custom_dimensions": {
                            ld.OPERATION: "save_availability",
                            ld.SENDER_HASH: mask_pii(sender_id),
                            "tipo_dia": tipo_dia,
                            "periodo_id": periodo_id,
                        }})
        except Exception:
            logger.error("falha ao salvar disponibilidade", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "save_availability",
                             ld.SENDER_HASH: mask_pii(sender_id),
                         }})

    def iniciar_modulo(self, sender_id):
        return self._enviar_bloco('SEMANA')

    def processar_resposta(self, step_atual, texto, sender_id):
        try:
            etapa_key = step_atual.split('_')[-1]
            config_etapa = self.ETAPAS.get(etapa_key)
        except Exception:
            return step_atual, {'tipo': 'texto', 'conteudo': "Erro interno. Digite OK para reiniciar."}

        if not config_etapa:
            return self.iniciar_modulo(sender_id)

        resp = texto.strip().upper()
        salvar_no_banco = False

        if resp in ['SIM', 'S', 'YES', 'CLARO', 'QUERO']:
            salvar_no_banco = True
        elif resp in ['NAO', 'N', 'NO', 'NUNCA']:
            salvar_no_banco = False
        else:
            return step_atual, {'tipo': 'texto', 'conteudo': "Resposta invalida. Por favor, responda com SIM ou NAO."}

        if salvar_no_banco:
            id_tipo_dia = config_etapa['id_db']
            periodo_padrao = 3

            thread_db = threading.Thread(
                target=self._salvar_disponibilidade,
                args=(id_tipo_dia, periodo_padrao, sender_id),
            )
            thread_db.start()
        else:
            logger.debug("usuario respondeu NAO, nada salvo",
                         extra={"custom_dimensions": {
                             ld.STEP: step_atual,
                             "etapa_nome": config_etapa['nome'],
                         }})

        proximo_step = config_etapa['proximo']

        if proximo_step == 'INICIAR_DOCUMENTOS':
            return 'AGUARDANDO_TIPO_DOC', {
                'tipo': 'sequencia',
                'mensagens': [
                    {'tipo': 'texto', 'conteudo': "Disponibilidade registrada!", 'delay': 1},
                    {'tipo': 'texto', 'conteudo': "*Etapa Final: Documentos*\n\nAgora precisamos das fotos dos seus documentos.", 'delay': 2},
                    {'tipo': 'template', 'sid': self.TEMPLATE_DOCS, 'variaveis': {}, 'delay': 1},
                ],
            }

        prox_etapa_key = proximo_step.split('_')[-1]
        return self._enviar_bloco(prox_etapa_key)
