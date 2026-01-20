import requests
from azure.storage.blob import BlobServiceClient
from app.core.config import Settings

class AzureBlobService:
    def __init__(self):
        settings = Settings()
        self.azure_connection_string = settings.get_secret("CONNECTION_STRING_AZURE_STORAGE")
        self.twilio_sid = settings.get_secret("TWILIO_ACCOUNT_SID")
        self.twilio_token = settings.get_secret("TWILIO_AUTH_TOKEN")

        if not all([self.azure_connection_string, self.twilio_sid, self.twilio_token]):
            print("⚠️ [AzureBlobService] AVISO: Variáveis de ambiente não encontradas!")
            print(f"   - Azure: {'OK' if self.azure_connection_string else 'Faltando'}")
            print(f"   - Twilio SID: {'OK' if self.twilio_sid else 'Faltando'}")
            print(f"   - Twilio Token: {'OK' if self.twilio_token else 'Faltando'}")
            self.blob_service_client = None
            return

        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(self.azure_connection_string)
        except Exception as e:
            print(f"⚠️ [Azure] Erro de Conexão na Inicialização: {e}")
            self.blob_service_client = None

    def upload_from_url(self, media_url, container_name, blob_name):
        """
        Baixa a imagem da URL do Twilio (com autenticação) e sobe para o Azure.
        """
        if not self.blob_service_client:
            print("⚠️ Cliente Azure não inicializado (Verifique suas credenciais).")
            return None

        try:
            print(f"📥 Baixando do Twilio: {media_url}...")
            response = requests.get(
                media_url, 
                stream=True, 
                auth=(self.twilio_sid, self.twilio_token)
            )
            if response.status_code == 200:
                container_client = self.blob_service_client.get_container_client(container_name)
                if not container_client.exists():
                    container_client.create_container()
                blob_client = container_client.get_blob_client(blob_name)
                blob_client.upload_blob(response.content, overwrite=True)
                print(f"✅ Upload Azure Sucesso: {blob_client.url}")
                return blob_client.url
            else:
                print(f"❌ Erro ao baixar mídia do Twilio. Status: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Erro crítico no upload: {e}")
            return None