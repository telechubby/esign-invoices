"""Sends the signed invoice PDF to its customer via Gmail SMTP.

Uses an SMTP App Password (not full OAuth) since this is a single-user tool
run interactively - simplest setup: enable 2-Step Verification on the Gmail
account, generate an App Password, paste it into Settings once.
"""
from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


class MailError(Exception):
    pass


@dataclass
class EmailTemplate:
    subject: str
    body: str

    def render(self, **kwargs: str) -> tuple[str, str]:
        try:
            return self.subject.format(**kwargs), self.body.format(**kwargs)
        except KeyError as exc:
            raise MailError(f"Непознат плејсхолдер во шаблонот: {exc}") from exc


@dataclass
class SmtpCredentials:
    address: str
    app_password: str
    host: str = GMAIL_SMTP_HOST
    port: int = GMAIL_SMTP_PORT


def send_invoice_email(
    creds: SmtpCredentials,
    to_address: str,
    subject: str,
    body: str,
    attachment_path: Path,
) -> None:
    msg = EmailMessage()
    msg["From"] = creds.address
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)

    data = attachment_path.read_bytes()
    msg.add_attachment(
        data,
        maintype="application",
        subtype="pdf",
        filename=attachment_path.name,
    )

    try:
        with smtplib.SMTP(creds.host, creds.port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(creds.address, creds.app_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "Неуспешна најава на Гмаил. Проверете дали користите App Password "
            "(не обична лозинка) и дали е вклучена двостепена автентикација."
        ) from exc
    except OSError as exc:
        raise MailError(f"Грешка при поврзување со Гмаил: {exc}") from exc
