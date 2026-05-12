import requests
from azure.storage.blob import BlobServiceClient

from app.core.config import Settings
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)


class AzureBlobService:
    def __init__(self):
        settings = Settings()
        self.azure_connection_string = settings.get_secret("CONNECTION-STRING-AZURE-STORAGE")
        # Chave usada como Bearer ("App <key>") pra baixar midia hospedada pelo Infobip.
        # Antes (Twilio): TWILIO-ACCOUNT-SID + TWILIO-AUTH-TOKEN como Basic Auth.
        self.infobip_api_key = settings.get_secret("INFOBIP-API-KEY")

        missing = [k for k, v in {
            "CONNECTION-STRING-AZURE-STORAGE": self.azure_connection_string,
            "INFOBIP-API-KEY": self.infobip_api_key,
        }.items() if not v]

        if missing:
            logger.warning("AzureBlobService: credenciais ausentes",
                           extra={"custom_dimensions": {
                               ld.OPERATION: "startup",
                               ld.COMPONENT: "azure_blob",
                               ld.MISSING_SECRETS: missing,
                           }})
            self.blob_service_client = None
            return

        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(self.azure_connection_string)
        except Exception:
            logger.error("erro de conexao com Azure Blob", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "startup",
                             ld.COMPONENT: "azure_blob",
                         }})
            self.blob_service_client = None

    def upload_from_url(self, media_url, container_name, blob_name):
        """Baixa midia da URL do Infobip e sobe pro Azure Blob Storage.

        REVISAR MANUALMENTE: dependendo da config do tenant Infobip, as URLs
        de midia podem ser publicas (sem auth) ou exigir o header
        Authorization: App <api_key>. Usamos a versao com auth por default.
        Se receber HTTP 401/403 ao baixar, remover o argumento headers.
        """
        if not self.blob_service_client:
            logger.warning("Azure blob client nao inicializado",
                           extra={"custom_dimensions": {ld.OPERATION: "upload_media"}})
            return None

        try:
            logger.debug("baixando midia do Infobip",
                         extra={"custom_dimensions": {
                             ld.OPERATION: "download_media",
                             "media_url": media_url,
                         }})
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
                logger.info("upload Azure Blob concluido",
                            extra={"custom_dimensions": {
                                ld.OPERATION: "upload_media",
                                "container": container_name,
                                "blob_name": blob_name,
                            }})
                return blob_client.url
            else:
                logger.warning("falha HTTP ao baixar midia",
                               extra={"custom_dimensions": {
                                   ld.OPERATION: "download_media",
                                   ld.EXTERNAL_STATUS: response.status_code,
                                   ld.EXTERNAL_SERVICE: "infobip",
                               }})
                return None
        except Exception:
            logger.error("erro critico no upload", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "upload_media",
                             "container": container_name,
                         }})
            return None
