import requests
from azure.storage.blob import BlobServiceClient
from app.core.config import Settings


class AzureBlobService:
    def __init__(self):
        settings = Settings()
        self.azure_connection_string = settings.get_secret("CONNECTION-STRING-AZURE-STORAGE")
        # Chave usada como Bearer ("App <key>") pra baixar midia hospedada pelo Infobip.
        # Antes (Twilio): TWILIO-ACCOUNT-SID + TWILIO-AUTH-TOKEN como Basic Auth.
        self.infobip_api_key = settings.get_secret("INFOBIP-API-KEY")

        if not all([self.azure_connection_string, self.infobip_api_key]):
            print("[AzureBlobService] AVISO: Variaveis de ambiente nao encontradas!")
            print(f"   - Azure: {'OK' if self.azure_connection_string else 'Faltando'}")
            print(f"   - Infobip API Key: {'OK' if self.infobip_api_key else 'Faltando'}")
            self.blob_service_client = None
            return

        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(self.azure_connection_string)
        except Exception as e:
            print(f"[Azure] Erro de Conexao na Inicializacao: {e}")
            self.blob_service_client = None

    def upload_from_url(self, media_url, container_name, blob_name):
        """Baixa midia da URL do Infobip e sobe pro Azure Blob Storage.

        REVISAR MANUALMENTE: dependendo da config do tenant Infobip, as URLs
        de midia podem ser publicas (sem auth) ou exigir o header
        Authorization: App <api_key>. Usamos a versao com auth por default
        (caso mais seguro). Se receber HTTP 401/403 ao baixar, remover o
        argumento `headers` desta chamada.
        """
        if not self.blob_service_client:
            print("Cliente Azure nao inicializado (Verifique suas credenciais).")
            return None

        try:
            print(f"Baixando midia do Infobip: {media_url}...")
            response = requests.get(
                media_url,
                stream=True,
                headers={"Authorization": f"App {self.infobip_api_key}"},
            )
            if response.status_code == 200:
                container_client = self.blob_service_client.get_container_client(container_name)
                if not container_client.exists():
                    container_client.create_container()
                blob_client = container_client.get_blob_client(blob_name)
                blob_client.upload_blob(response.content, overwrite=True)
                print(f"Upload Azure Sucesso: {blob_client.url}")
                return blob_client.url
            else:
                print(f"Erro ao baixar midia do Infobip. Status: {response.status_code}")
                return None
        except Exception as e:
            print(f"Erro critico no upload: {e}")
            return None
