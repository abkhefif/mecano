"""PERF-07: RGPD-compliant log masking utilities.

Prevents PII (emails, phone numbers) from leaking into INFO-level logs
which may be shipped to third-party log aggregators (Datadog, Sentry, etc.).
"""


def mask_email(email: str | None) -> str:
    """Mask an email address for logging: 'user@domain.com' -> 'u***@domain.com'."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    if len(local) <= 1:
        return f"{local}***@{domain}"
    return f"{local[0]}***@{domain}"
