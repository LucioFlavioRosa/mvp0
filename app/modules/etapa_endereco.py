from app.modules.common import GeradorResposta
from app.core.database import DatabaseManager
from app.core.telemetry import get_logger, mask_pii
from app.core import log_dimensions as ld
import requests
import re
import googlemaps
from app.core.config import Settings

logger = get_logger(__name__)


class EtapaEndereco:
    def __init__(self):
        self.db = DatabaseManager()
        settings = Settings()
        api_key = settings.get_secret('GOOGLE-MAPS-API-KEY')

        if api_key:
            try:
                self.gmaps = googlemaps.Client(key=api_key)
                logger.info("Google Maps Client inicializado",
                            extra={"custom_dimensions": {
                                ld.OPERATION: "startup",
                                ld.COMPONENT: "google_maps",
                            }})
            except Exception:
                logger.error("erro ao iniciar Google Maps", exc_info=True,
                             extra={"custom_dimensions": {
                                 ld.OPERATION: "startup",
                                 ld.COMPONENT: "google_maps",
                             }})
                self.gmaps = None
        else:
            logger.warning("GOOGLE-MAPS-API-KEY ausente, geocode desativado",
                           extra={"custom_dimensions": {
                               ld.OPERATION: "startup",
                               ld.MISSING_SECRETS: ["GOOGLE-MAPS-API-KEY"],
                           }})
            self.gmaps = None

        # ID do Template que inicia a proxima etapa (Habilidades)
        self.TEMPLATE_HIDROMETRO = "HX24e1bcb7e514d6fca272f38691c76a33"

    def _consultar_viacep(self, cep):
        try:
            url = f"https://viacep.com.br/ws/{cep}/json/"
            res = requests.get(url, timeout=5)
            dados = res.json()
            if 'erro' in dados:
                return None
            return dados
        except Exception:
            return None

    def _obter_lat_long(self, rua, numero, bairro, cidade, cep):
        """Usa googlemaps pra obter latitude e longitude. Retorna (lat, lng) ou (None, None)."""
        if not self.gmaps:
            logger.warning("Google Maps Client inativo",
                           extra={"custom_dimensions": {ld.OPERATION: "geocode"}})
            return None, None

        endereco_completo = f"{rua}, {numero} - {bairro}, {cidade}, {cep}, Brasil"
        logger.debug("buscando endereco no Google Maps",
                     extra={"custom_dimensions": {
                         ld.OPERATION: "geocode",
                         "endereco": endereco_completo,
                     }})

        try:
            result = self.gmaps.geocode(endereco_completo)

            if result and len(result) > 0:
                location = result[0]['geometry']['location']
                return location['lat'], location['lng']
            else:
                logger.warning("Google Maps: endereco nao encontrado",
                               extra={"custom_dimensions": {
                                   ld.OPERATION: "geocode",
                                   ld.RESULT: "not_found",
                               }})
                return None, None

        except Exception:
            logger.error("erro na API do Google Maps", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "geocode",
                             ld.EXTERNAL_SERVICE: "google_maps",
                         }})
            return None, None

    def processar_cep(self, texto, sender_id):
        cep_limpo = re.sub(r'\D', '', texto)
        if len(cep_limpo) != 8:
            return 'AGUARDANDO_CEP', {'tipo': 'texto', 'conteudo': "CEP deve ter 8 digitos numericos. Tente novamente:"}

        dados_cep = self._consultar_viacep(cep_limpo)
        if not dados_cep:
            return 'AGUARDANDO_CEP', {'tipo': 'texto', 'conteudo': f"O CEP {cep_limpo} nao foi encontrado.\nVerifique e envie novamente:"}

        cidade = dados_cep.get('localidade', '')
        uf = dados_cep.get('uf', '')
        bairro_api = dados_cep.get('bairro', '')
        rua_api = dados_cep.get('logradouro', '')

        sql = "UPDATE PARCEIROS_PERFIL SET CEP=?, Cidade=?, Bairro=?, Rua=? WHERE WhatsAppID=?"
        self.db.execute_write(sql, (cep_limpo, cidade, bairro_api, rua_api, sender_id))

        msg = f"Cidade localizada: {cidade}-{uf}."

        if bairro_api:
            msg += f"\n\nO sistema identificou o bairro *{bairro_api}*.\nSe estiver certo, digite OK. Se nao, digite o nome correto do *Bairro*:"
        else:
            msg += "\n\nAgora digite o nome do seu *Bairro*:"

        return 'AGUARDANDO_BAIRRO', {'tipo': 'texto', 'conteudo': msg}

    def processar_bairro(self, texto, sender_id):
        resposta = texto.strip()

        if resposta.upper() not in ['OK', 'SIM', 'S', 'CONFIRMO']:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET Bairro=? WHERE WhatsAppID=?", (resposta, sender_id))

        row = self.db.execute_read_one("SELECT Rua FROM PARCEIROS_PERFIL WHERE WhatsAppID=?", (sender_id,))
        rua_salva = row[0] if row else ""

        msg = "Certo, bairro registrado."
        if rua_salva:
            msg += f"\n\nIdentificamos a rua: *{rua_salva}*.\nDigite OK para confirmar ou digite o nome correto da *Rua*:"
        else:
            msg += "\n\nAgora digite o nome da sua *Rua*:"

        return 'AGUARDANDO_RUA', {'tipo': 'texto', 'conteudo': msg}

    def processar_rua(self, texto, sender_id):
        resposta = texto.strip()

        if resposta.upper() not in ['OK', 'SIM', 'S', 'CONFIRMO']:
            self.db.execute_write("UPDATE PARCEIROS_PERFIL SET Rua=? WHERE WhatsAppID=?", (resposta, sender_id))

        return 'AGUARDANDO_NUMERO', {'tipo': 'texto', 'conteudo': "Perfeito. Por fim, digite o *Numero* da casa:"}

    def processar_numero(self, texto, sender_id):
        numero = texto.strip()

        sql_busca = "SELECT Rua, Cidade, Bairro, CEP FROM PARCEIROS_PERFIL WHERE WhatsAppID=?"
        row = self.db.execute_read_one(sql_busca, (sender_id,))
        lat, long = None, None

        if row:
            rua, cidade_uf, bairro, cep = row
            cidade = cidade_uf.split('-')[0].strip() if '-' in cidade_uf else cidade_uf
            lat, long = self._obter_lat_long(rua, numero, bairro, cidade, cep)

        if lat and long:
            logger.debug("GPS encontrado",
                         extra={"custom_dimensions": {
                             ld.OPERATION: "geocode",
                             ld.SENDER_HASH: mask_pii(sender_id),
                         }})
            sql_update = """UPDATE PARCEIROS_PERFIL SET Numero=?, Geo_Base=geography::Point(?, ?, 4326) WHERE WhatsAppID=?"""
            self.db.execute_write(sql_update, (numero, lat, long, sender_id))
        else:
            logger.warning("GPS nao encontrado, salvando apenas numero",
                           extra={"custom_dimensions": {
                               ld.OPERATION: "geocode",
                               ld.RESULT: "not_found",
                               ld.SENDER_HASH: mask_pii(sender_id),
                           }})
            sql_update = "UPDATE PARCEIROS_PERFIL SET Numero=? WHERE WhatsAppID=?"
            self.db.execute_write(sql_update, (numero, sender_id))

        return 'AGUARDANDO_DISTANCIA', {'tipo': 'texto', 'conteudo': "Endereco salvo!\n\nAgora, qual a *distancia maxima (em KM)* que voce aceita se deslocar ate o servico?\n\n(Digite apenas o numero, ex: 15)"}

    def processar_distancia(self, texto, sender_id):
        distancia_str = re.sub(r'\D', '', texto)

        if not distancia_str:
            return 'AGUARDANDO_DISTANCIA', {'tipo': 'texto', 'conteudo': "Por favor, digite apenas numeros para a distancia em KM (ex: 20)."}

        distancia_km = int(distancia_str)

        sql = "UPDATE PARCEIROS_PERFIL SET DistanciaMaximaKm=? WHERE WhatsAppID=?"
        self.db.execute_write(sql, (distancia_km, sender_id))

        return 'AGUARDANDO_HABILIDADE_1', {
            'tipo': 'sequencia',
            'mensagens': [
                {'tipo': 'texto', 'conteudo': f"Registrado raio de {distancia_km}km.", 'delay': 1},
                {'tipo': 'texto', 'conteudo': "*Nova Etapa: Habilidades*\n\nAgora vamos verificar quais servicos voce realiza.", 'delay': 2},
                {'tipo': 'template', 'sid': self.TEMPLATE_HIDROMETRO, 'variaveis': {}, 'delay': 1},
            ],
        }
