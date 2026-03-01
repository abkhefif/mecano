"""Email verification service using Resend API.

Generates JWT-based verification tokens and sends emails via Resend.
In dev mode (no RESEND_API_KEY), logs a warning and skips sending.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from html import escape  # noqa: F401 — M-02: available for escaping user values in email templates

import httpx
import structlog
import jwt

from app.config import settings
from app.utils.log_mask import mask_email

logger = structlog.get_logger()

RESEND_API_URL = "https://api.resend.com/emails"

_email_client: httpx.AsyncClient | None = None


def _get_email_client() -> httpx.AsyncClient:
    global _email_client
    if _email_client is None or _email_client.is_closed:
        _email_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
    return _email_client


def generate_verification_code() -> str:
    """Generate a cryptographically secure 6-digit OTP code.

    FINDING-L01: Use the full [000000, 999999] range (zero-padded) instead of
    [100000, 999999].  The previous implementation excluded ~11 % of the key
    space, reducing entropy by ~3.3 bits.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def create_email_verification_token(email: str) -> str:
    """Generate a JWT token for email verification (24h expiry)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "exp": now + timedelta(hours=24),
        "iat": now,
        "iss": "emecano",
        "type": "email_verify",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_email_verification_token(token: str) -> str | None:
    """Decode an email verification token and return the email, or None if invalid."""
    payload = decode_email_verification_token_full(token)
    return payload.get("sub") if payload else None


def decode_email_verification_token_full(token: str) -> dict | None:
    """Decode an email verification token and return the full payload, or None if invalid.

    SEC-R01: Single decode — callers should use this instead of decoding twice.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
        if payload.get("type") != "email_verify":
            return None
        return payload
    except Exception:
        return None


async def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    """Send a password reset email via Resend API.

    If RESEND_API_KEY is not set, logs a warning and returns False (dev mode).
    Returns True if the email was sent successfully.
    """
    if not settings.RESEND_API_KEY:
        logger.warning(
            "resend_api_key_not_set",
            msg="RESEND_API_KEY not configured, skipping email send (dev mode)",
            email=mask_email(to_email),
        )
        return False

    # L-4: Escape link to prevent XSS if token format ever changes
    reset_link = escape(f"{settings.FRONTEND_URL}/reset-password?token={reset_token}")

    payload = {
        "from": "eMecano <noreply@emecano.fr>",
        "to": [to_email],
        "subject": "Reinitialisation de votre mot de passe - eMecano",
        "html": (
            "<h2>Reinitialisation de mot de passe</h2>"
            "<p>Vous avez demande la reinitialisation de votre mot de passe.</p>"
            "<p>Cliquez sur le lien ci-dessous pour definir un nouveau mot de passe :</p>"
            f'<p><a href="{reset_link}">Reinitialiser mon mot de passe</a></p>'
            "<p>Ce lien expire dans 1 heure.</p>"
            "<p>Si vous n'avez pas fait cette demande, ignorez cet email.</p>"
        ),
    }

    try:
        client = _get_email_client()
        response = await client.post(
            RESEND_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        if response.is_success:
            logger.info("password_reset_email_sent", email=mask_email(to_email))
            return True
        else:
            logger.error(
                "password_reset_email_failed",
                email=mask_email(to_email),
                status_code=response.status_code,
            )
            return False
    except Exception as exc:
        logger.error("password_reset_email_error", email=mask_email(to_email), error=str(exc))
        return False


async def send_verification_email(email: str, token: str, code: str | None = None) -> bool:
    """Send a verification email via Resend API.

    If RESEND_API_KEY is not set, logs a warning and returns False (dev mode).
    Returns True if the email was sent successfully.

    Args:
        email: Recipient email address.
        token: JWT verification token (for web link fallback).
        code: 6-digit OTP code displayed prominently in the email.
    """
    if not settings.RESEND_API_KEY:
        logger.warning(
            "resend_api_key_not_set",
            msg="RESEND_API_KEY not configured, skipping email send (dev mode)",
            email=mask_email(email),
        )
        return False

    # L-4: Escape link to prevent XSS if token format ever changes
    verification_link = escape(f"{settings.FRONTEND_URL}/verify?token={token}")

    # Build HTML body — OTP code shown prominently, link as fallback
    if code:
        html_body = (
            "<h2>Bienvenue sur eMecano !</h2>"
            "<p>Voici votre code de verification :</p>"
            '<div style="text-align:center;margin:24px 0;">'
            f'<span style="font-size:32px;font-weight:bold;letter-spacing:8px;'
            f'background:#f0f0f0;padding:16px 32px;border-radius:8px;">{escape(code)}</span>'
            "</div>"
            "<p>Saisissez ce code dans l'application pour verifier votre email.</p>"
            "<p>Ce code expire dans 24 heures.</p>"
            "<p style='color:#888;font-size:12px;margin-top:24px;'>"
            "Vous pouvez aussi "
            f'<a href="{verification_link}">cliquer ici</a> pour verifier.</p>'
            "<p>Si vous n'avez pas cree de compte, ignorez cet email.</p>"
        )
    else:
        html_body = (
            "<h2>Bienvenue sur eMecano !</h2>"
            "<p>Cliquez sur le lien ci-dessous pour verifier votre adresse email :</p>"
            f'<p><a href="{verification_link}">Verifier mon email</a></p>'
            "<p>Ce lien expire dans 24 heures.</p>"
            "<p>Si vous n'avez pas cree de compte, ignorez cet email.</p>"
        )

    payload = {
        "from": "eMecano <noreply@emecano.fr>",
        "to": [email],
        "subject": "Votre code de verification eMecano",
        "html": html_body,
    }

    try:
        client = _get_email_client()
        response = await client.post(
            RESEND_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        if response.is_success:
            logger.info("verification_email_sent", email=mask_email(email))
            return True
        else:
            logger.error(
                "verification_email_failed",
                email=mask_email(email),
                status_code=response.status_code,
            )
            return False
    except Exception as exc:
        logger.error("verification_email_error", email=mask_email(email), error=str(exc))
        return False
