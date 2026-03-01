import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


async def send_verification_email(to_email: str, token: str) -> None:
    verify_url = f"{settings.frontend_url}/verify?token={token}"
    subject = "Verify your Trial Whisperer account"
    body = f"Please verify your email by opening: {verify_url}"

    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
        logger.info("verification_email", extra={"to": to_email, "verify_url": verify_url})
        print({"event": "verification_email", "to": to_email, "verify_url": verify_url})
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.send_message(msg)
