from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    async def send(self, email: Email) -> None: ...


class SmtpEmailSender:
    def __init__(self, host: str, port: int, sender: str) -> None:
        self.host = host
        self.port = port
        self.sender = sender

    async def send(self, email: Email) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.body)
        await aiosmtplib.send(message, hostname=self.host, port=self.port)
