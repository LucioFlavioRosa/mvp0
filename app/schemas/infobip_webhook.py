"""
Schemas Pydantic do payload de webhook inbound do Infobip WhatsApp.

A documentação oficial do Infobip cobre mais tipos de mensagem (LOCATION,
CONTACT, INTERACTIVE_*). Aqui mantemos apenas TEXT e IMAGE — adicionar
outros conforme o bot precisar.
"""

from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal


class InfobipMessageText(BaseModel):
    type: Literal["TEXT"]
    text: str


class InfobipMessageImage(BaseModel):
    type: Literal["IMAGE"]
    url: str
    caption: Optional[str] = None


InfobipMessage = Union[InfobipMessageText, InfobipMessageImage]


class InfobipContact(BaseModel):
    name: Optional[str] = None


class InfobipResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sender: str = Field(alias="from")
    to: str
    message_id: str = Field(alias="messageId")
    received_at: datetime = Field(alias="receivedAt")
    message: InfobipMessage = Field(discriminator="type")
    contact: Optional[InfobipContact] = None


class InfobipInboundPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    results: list[InfobipResult]
    message_count: int = Field(alias="messageCount")
