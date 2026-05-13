"""
Schema Pydantic para mensagens na Dead-Letter Queue (Azure Storage Queue).

Politica:
- Cada mensagem vive 1 ciclo: enqueue -> admin retry manual -> delete obrigatorio.
- Sem retry automatico, sem fantasmas reaparecendo via visibility timeout.
- Apenas 2 tentativas total (ambas via retry transient no caminho normal);
  o admin retry e UMA chance extra sob demanda humana, sempre seguido de delete.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DLQMessage(BaseModel):
    """Mensagem persistida na fila Azure Storage `outbound-dlq`."""

    operation: str = Field(..., description="Nome da operacao que falhou (ex: send_text, download_media)")
    external_service: str = Field(..., description="Servico externo alvo (ex: infobip, azure_blob)")
    payload: dict[str, Any] = Field(..., description="Argumentos da chamada original, suficientes para retry")
    sender_hash: Optional[str] = Field(None, description="Hash PII do destinatario (mask_pii)")
    attempts: int = Field(..., ge=1, description="Numero de tentativas que falharam antes desta mensagem cair na DLQ")
    last_error: str = Field(..., description="Texto curto do erro que disparou o enqueue")
    errored_at: datetime = Field(..., description="UTC do momento que falhou")
    operation_id: Optional[str] = Field(None, description="Correlation ID da request original (App Insights)")
