import smtplib
import ssl
from email.message import EmailMessage

from app.config import (
    SMTP_ENABLED,
    SMTP_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_STARTTLS,
    SMTP_USERNAME,
    SMTP_USE_SSL,
)

SMTP_TIMEOUT_SECONDS = 10


class EmailDeliveryError(RuntimeError):
    pass


def send_email(recipient: str, subject: str, body: str) -> None:
    if not SMTP_ENABLED:
        raise EmailDeliveryError("Email delivery is not configured.")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = recipient
    message.set_content(body)
    try:
        smtp_class = smtplib.SMTP_SSL if SMTP_USE_SSL else smtplib.SMTP
        connection_options = (
            {"context": ssl.create_default_context()} if SMTP_USE_SSL else {}
        )
        with smtp_class(
            SMTP_HOST,
            SMTP_PORT,
            timeout=SMTP_TIMEOUT_SECONDS,
            **connection_options,
        ) as server:
            if SMTP_STARTTLS and not SMTP_USE_SSL:
                server.starttls(context=ssl.create_default_context())
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("Email delivery failed.") from exc
