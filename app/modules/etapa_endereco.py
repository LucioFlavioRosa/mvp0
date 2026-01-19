from app.modules.common import GeradorResposta
from app.core.database import DatabaseManager
import requests
import re
import os
import googlemaps # 🟢 Biblioteca oficial do Google Maps

class EtapaEndereco:
    def __init__(self):
        self.db = DatabaseManager()
        
        # 🟢 Configuração do Google Maps
        # A chave deve estar carregada no os.environ (ver passo anterior do Colab)
        api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
        
        if api_key:
            try:
                self.gmaps = googlemaps.Client(key=api_key)
                print("✅ Google Maps Client inicializado com sucesso.")
            except Exception as e:
                print(f"❌ Erro ao iniciar Google Maps: {e}")
                self.gmaps = None
        else:
            print("⚠️ AVISO: GOOGLE_MAPS_API_KEY não encontrada. Geolocalização não funcionará.")
            self.gmaps = None
        
        # ID do Template que inicia a próxima etapa (Habilidades)
        self.TEMPLATE_HIDROMETRO = "HX24e1bcb7e514d6fca272f38691c76a33" 

    def _consultar_viacep(self, cep):
        try:
            url = f"https://viacep.com.br/ws/{cep}/json/"
            res = requests.get(url, timeout=5)
            dados = res.json()
            if 'erro' in dados: return None
            return dados
        except:
            return None

    def _obter_lat_long(self, rua, numero, bairro, cidade, cep):
        """
        Usa a biblioteca oficial 'googlemaps' para obter latitude e longitude.
        Retorna (lat, lng) ou (None, None).
        """
        if not self.gmaps:
            print("❌ Google Maps Client não está ativo.")
            return None, None

        # Monta string de busca robusta
        endereco_completo = f"{rua}, {numero} - {bairro}, {cidade}, {cep}, Brasil"
        print(f"🌍 Buscando no Google Maps: {endereco_completo}")

        try:
            # 🟢 Chamada oficial da API
            result = self.gmaps.geocode(endereco_completo)
            
            # Verifica se houve resultado
            if result and len(result) > 0:
                # O Google retorna uma lista, pegamos o primeiro (melhor match)
                location = result[0]['geometry']['location']
                lat = location['lat']
                lng = location['lng']
                return lat, lng
            else:
                print("⚠️ Google Maps: Endereço não encontrado.")
                return None, None

        except Exception as e:
            print(f"🔥 Erro na API do Google Maps: {e}")
            return None, None

    def processar_cep(self, texto, sender_id):
        # 1. Validação
        cep_limpo = re.sub(r'\D', '', texto)
        if len(cep_limpo) != 8:
            return 'AGUARDANDO_CEP', {'tipo': 'texto', 'conteudo': "❌ CEP deve ter 8 dígitos numéricos. Tente novamente:"}

        # 2. Consulta ViaCEP
        dados_cep = self._consultar_viacep(cep_limpo)
        if not dados_cep:
            return 'AGUARDANDO_CEP', {'tipo': 'texto', 'conteudo': f"❌ O CEP *{cep_limpo}* não foi encontrado.\nVerifique e envie novamente:"}

        # 3. Extrai dados (Prioriza Cidade/UF)
        cidade = dados_cep.get('localidade', '')
        uf = dados_cep.get('uf', '')
        bairro_api = dados_cep.get('bairro', '') 
        rua_api = dados_cep.get('logradouro', '') 

        # 4. Salva no banco (Atualiza o que veio da API)
        sql = "UPDATE PARCEIROS_PERFIL SET CEP=?, Cidade=?, Bairro=?, Rua=? WHERE WhatsAppID=?"
        self.db.execute_write(sql, (cep_limpo, f"{cidade}-{uf}", bairro_api, rua_api, sender_id))

        # 5. Lógica da Sequência: CEP -> BAIRRO
        msg = f"📍 Cidade localizada: {cidade}-{uf}."
        
        if bairro_api:
            msg += f"\n\nO sistema identificou o bairro *{bairro_api}*.\nSe estiver certo, digite OK. Se não, digite o nome correto do *Bairro*:"
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

        return 'AGUARDANDO_NUMERO', {'tipo': 'texto', 'conteudo': "Perfeito. Por fim, digite o *Número* da casa:"}

    def processar_numero(self, texto, sender_id):
        numero = texto.strip()
        
        # Recupera dados salvos
        sql_busca = "SELECT Rua, Cidade, Bairro, CEP FROM PARCEIROS_PERFIL WHERE WhatsAppID=?"
        row = self.db.execute_read_one(sql_busca, (sender_id,))
        lat, long = None, None
        
        if row:
            rua, cidade_uf, bairro, cep = row
            # Separa Cidade de UF se necessário (ex: "Belém-PA" -> "Belém")
            cidade = cidade_uf.split('-')[0].strip() if '-' in cidade_uf else cidade_uf
            
            # 🟢 CHAMADA AO GOOGLE MAPS (Novo Método)
            lat, long = self._obter_lat_long(rua, numero, bairro, cidade, cep)
        
        if lat and long:
            print(f"✅ GPS Encontrado (Google): {lat}, {long}")
            sql_update = """UPDATE PARCEIROS_PERFIL SET Numero=?, Geo_Base=geography::Point(?, ?, 4326) WHERE WhatsAppID=?"""
            self.db.execute_write(sql_update, (numero, lat, long, sender_id))
        else:
            print("⚠️ GPS não encontrado. Salvando apenas número.")
            sql_update = "UPDATE PARCEIROS_PERFIL SET Numero=? WHERE WhatsAppID=?"
            self.db.execute_write(sql_update, (numero, sender_id))
        
        return 'AGUARDANDO_DISTANCIA', {'tipo': 'texto', 'conteudo': "📍 Endereço salvo!\n\nAgora, qual a *distância máxima (em KM)* que você aceita se deslocar até o serviço?\n\n(Digite apenas o número, ex: 15)"}
        
    def processar_distancia(self, texto, sender_id):
        # 1. Limpa o texto para pegar só números (ex: "50km" vira "50")
        distancia_str = re.sub(r'\D', '', texto)
        
        if not distancia_str:
            return 'AGUARDANDO_DISTANCIA', {'tipo': 'texto', 'conteudo': "⚠️ Por favor, digite apenas números para a distância em KM (ex: 20)."}
        
        distancia_km = int(distancia_str)
        
        # 2. Salva no Banco
        sql = "UPDATE PARCEIROS_PERFIL SET DistanciaMaximaKm=? WHERE WhatsAppID=?"
        self.db.execute_write(sql, (distancia_km, sender_id))
        
        # 3. Transição para Habilidades
        return 'AGUARDANDO_HABILIDADE_1', {
            'tipo': 'sequencia',
            'mensagens': [
                {
                    'tipo': 'texto', 
                    'conteudo': f"✅ Registrado raio de {distancia_km}km.", 
                    'delay': 1
                },
                {
                    'tipo': 'texto', 
                    'conteudo': "🛠️ *Nova Etapa: Habilidades*\n\nAgora vamos verificar quais serviços você realiza.", 
                    'delay': 2
                },
                {
                    'tipo': 'template',
                    'sid': self.TEMPLATE_HIDROMETRO,
                    'variaveis': {},
                    'delay': 1
                }
            ]
        }