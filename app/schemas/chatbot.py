from pydantic import BaseModel
from typing import List, Optional

class DispatchRequest(BaseModel):
    pedido_uuid: str
    parceiros: List[str]

class SendMessageRequest(BaseModel):
    parceiro_uuid: str
    mensagem: str
