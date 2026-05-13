"""
Servico de upload de midia recebida do Infobip para o Azure Blob Storage.

Download da midia (HTTP outbound pro Infobip) tem retry transient via
@transient_retry e, em caso de falha pos-retry, persiste na DLQ
(Azure Storage Queue) antes de retornar None.
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests
from azure.storage.blob import BlobServiceClient

from app.core.config import Settings
from app.core.retry import transient_retry
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld
from app.integrations.dlq import DLQClient
from app.schemas.dlq import DLQMessage

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

        # DLQ pra falhas pos-retry no download de midia
        self._dlq = DLQClient()

    @transient_retry
    def _download_midia(self, media_url):
        """Baixa midia do Infobip. Decorado com retry transient (2 tentativas).

        Levanta requests.HTTPError em 4xx/5xx (caller decide o que fazer com 4xx;
        5xx ja sao re-tentadas pelo transient_retry).
        """
        logger.debug("baixando midia do Infobip",
                     extra={"custom_dimensions": {
                         ld.OPERATION: "download_media",
                         "media_url": media_url,
                     }})
        response = requests.get(
            media_url,
            stream=True,
            timeout=10,
            headers={"Authorization": f"App {self.infobip_api_key}"},
        )
        response.raise_for_status()
        return response

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

        # Download (com retry transient via decorator)
        try:
            response = self._download_midia(media_url)
        except requests.HTTPError as exc:
            # 4xx propaga aqui (5xx ja foi re-tentado pelo transient_retry).
            # 4xx geralmente eh URL invalida ou auth/permissao - WARNING.
            status_code = exc.response.status_code if exc.response is not None else None
            logger.warning("falha HTTP ao baixar midia",
                           extra={"custom_dimensions": {
                               ld.OPERATION: "download_media",
                               ld.EXTERNAL_STATUS: status_code,
                               ld.EXTERNAL_SERVICE: "infobip",
                           }})
            # 4xx geralmente nao adianta retry manual; mas enfileiramos
            # pra visibilidade humana (URL pode ter sido publica e mudou).
            self._enqueue_dlq(media_url, container_name, blob_name, exc, attempts=1)
            return None
        except Exception as exc:
            logger.error("erro critico no download da midia", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "download_media",
                         }})
            self._enqueue_dlq(media_url, container_name, blob_name, exc, attempts=2)
            return None

        # Upload pro Azure Blob
        try:
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
        except Exception:
            logger.error("erro critico no upload pro Azure Blob", exc_info=True,
                         extra={"custom_dimensions": {
                             ld.OPERATION: "upload_media",
                             "container": container_name,
                         }})
            return None

    def _enqueue_dlq(self, media_url, container_name, blob_name, exc, attempts):
        """Persiste falha de download/upload na DLQ pra investigacao humana."""
        msg = DLQMessage(
            operation="download_media",
            external_service="infobip",
            payload={
                "media_url": media_url,
                "container_name": container_name,
                "blob_name": blob_name,
            },
            sender_hash=None,
            attempts=attempts,
            last_error=f"{type(exc).__name__}: {str(exc)[:200]}",
            errored_at=datetime.now(timezone.utc),
        )
        self._dlq.enqueue(msg)
