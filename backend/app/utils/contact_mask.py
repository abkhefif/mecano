import re

# AUD-M08: Pre-compile regex patterns at module level to avoid recompilation on each call
_MAX_INPUT_LENGTH = 10000  # Limit input to prevent ReDoS on pathological strings

_RE_EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_RE_EMAIL_TEXT = re.compile(r'[\w.+-]+\s+(?:at|AT|chez)\s+[\w-]+\.[\w.-]+')
# BUG-008: French phone numbers with stricter pattern (06, 07, +33, etc.)
_RE_PHONE_FR = re.compile(r'\b(?:(?:\+33|0033|0)\s*[1-9])(?:[\s.\-]?\d{2}){4}\b')
# Generic phone patterns (7+ digits with optional separators)
_RE_PHONE_GENERIC = re.compile(r'\b\d[\d\s.\-]{8,}\d\b')
# WhatsApp links (wa.me/...)
_RE_WHATSAPP = re.compile(r'wa\.me/[\w+\-]+')
# Telegram links (t.me/...)
_RE_TELEGRAM = re.compile(r't\.me/[\w+\-]+')
# Social media handles (@username)
_RE_HANDLE = re.compile(r'@\w{2,}')
# Instagram, WhatsApp, Telegram, etc. keywords
_RE_SOCIAL_KEYWORDS = re.compile(
    r'\b(?:insta(?:gram)?|whatsapp|telegram|snap(?:chat)?|facebook|fb|messenger)\b',
    flags=re.IGNORECASE,
)


def mask_contacts(text: str) -> str:
    """Mask emails, phone numbers, and social media handles in text."""
    if len(text) > _MAX_INPUT_LENGTH:
        text = text[:_MAX_INPUT_LENGTH]

    text = _RE_EMAIL.sub('[EMAIL MASQUE]', text)
    text = _RE_EMAIL_TEXT.sub('[EMAIL MASQUE]', text)
    text = _RE_PHONE_FR.sub('[TELEPHONE MASQUE]', text)
    text = _RE_PHONE_GENERIC.sub('[TELEPHONE MASQUE]', text)
    text = _RE_WHATSAPP.sub('[CONTACT MASQUE]', text)
    text = _RE_TELEGRAM.sub('[CONTACT MASQUE]', text)
    text = _RE_HANDLE.sub('[CONTACT MASQUE]', text)
    text = _RE_SOCIAL_KEYWORDS.sub('[CONTACT MASQUE]', text)
    return text
