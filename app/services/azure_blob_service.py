import os
import requests
from azure.storage.blob import BlobServiceClient
from requests.auth import HTTPBasicAuth

class AzureBlobService:
    def __init__(self):
        # 1. Recupera as credenciais das Variáveis de Ambiente
        self.azure_connection_string = os.environ.get("CONNECTION_STRING_AZURE_STORAGE")
        self.twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_token = os.environ.get("TWILIO_AUTH_TOKEN")

        # Validação simples para evitar erro silencioso
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
            
            # Faz o download autenticado no Twilio
            response = requests.get(
                media_url, 
                stream=True, 
                auth=(self.twilio_sid, self.twilio_token)
            )
            
            if response.status_code == 200:
                # Conecta ao container
                container_client = self.blob_service_client.get_container_client(container_name)
                if not container_client.exists():
                    container_client.create_container()

                # Faz o Upload para o Azure
                blob_client = container_client.get_blob_client(blob_name)
                blob_client.upload_blob(response.content, overwrite=True)
                
                print(f"✅ Upload Azure Sucesso: {blob_client.url}")
                return blob_client.url
            
            else:
                print(f"❌ Erro ao baixar mídia do Twilio. Status: {response.status_code}")
                # print(f"Resposta: {response.text}") # Descomente para debug
                return None
                
        except Exception as e:
            print(f"❌ Erro crítico no upload: {e}")
            return None