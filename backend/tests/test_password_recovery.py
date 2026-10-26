from email.message import EmailMessage

from app.services import email_delivery, password_recovery


class SMTPStub:
    def __init__(self, host, port, timeout, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.options = kwargs
        self.started_tls = False
        self.credentials = None
        self.message = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def starttls(self, context):
        self.started_tls = context is not None

    def login(self, username, password):
        self.credentials = (username, password)

    def send_message(self, message):
        self.message = message


def configure_smtp(monkeypatch):
    monkeypatch.setattr(email_delivery, "SMTP_ENABLED", True)
    monkeypatch.setattr(email_delivery, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(email_delivery, "SMTP_PORT", 587)
    monkeypatch.setattr(email_delivery, "SMTP_USERNAME", "mailer")
    monkeypatch.setattr(email_delivery, "SMTP_PASSWORD", "test-smtp-secret")
    monkeypatch.setattr(
        email_delivery, "SMTP_FROM_EMAIL", "no-reply@example.test"
    )


def test_recovery_email_uses_starttls_and_sends_link(monkeypatch):
    configure_smtp(monkeypatch)
    monkeypatch.setattr(email_delivery, "SMTP_STARTTLS", True)
    monkeypatch.setattr(email_delivery, "SMTP_USE_SSL", False)
    connection = SMTPStub("smtp.example.test", 587, 10)
    monkeypatch.setattr(
        email_delivery.smtplib, "SMTP", lambda *args, **kwargs: connection
    )

    password_recovery.send_recovery_email(
        "user@example.test",
        "https://workspace.example.test/reset-password#token=secret-token",
    )

    assert connection.started_tls
    assert connection.credentials == ("mailer", "test-smtp-secret")
    assert isinstance(connection.message, EmailMessage)
    assert connection.message["To"] == "user@example.test"
    assert "secret-token" in connection.message.get_content()


def test_recovery_email_uses_implicit_tls_without_starttls(monkeypatch):
    configure_smtp(monkeypatch)
    monkeypatch.setattr(email_delivery, "SMTP_STARTTLS", False)
    monkeypatch.setattr(email_delivery, "SMTP_USE_SSL", True)
    connection = SMTPStub("smtp.example.test", 465, 10)

    def smtp_ssl(*_args, **kwargs):
        connection.options = kwargs
        return connection

    monkeypatch.setattr(email_delivery.smtplib, "SMTP_SSL", smtp_ssl)

    password_recovery.send_recovery_email("user@example.test", None)

    assert connection.options["context"] is not None
    assert not connection.started_tls
    assert connection.message["To"] == "user@example.test"
    assert connection.message["Subject"] == "InkLoom workspace password recovery"
