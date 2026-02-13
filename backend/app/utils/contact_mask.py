import re


def mask_contacts(text: str) -> str:
    """Mask emails, phone numbers, and social media handles in text."""
    # Email (standard format)
    text = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '[EMAIL MASQUE]', text)
    # Email ("at" written as text, e.g. "user at domain.com")
    text = re.sub(
        r'[\w.+-]+\s+(?:at|AT|chez)\s+[\w-]+\.[\w.-]+',
        '[EMAIL MASQUE]',
        text,
    )
    # French phone numbers (06, 07, +33, etc.) with spaces, dots, or dashes
    text = re.sub(r'(?:\+33|0033|0)\s*[1-9](?:[\s.\-]*\d{2}){4}', '[TELEPHONE MASQUE]', text)
    # Generic phone patterns (7+ digits with optional separators)
    text = re.sub(r'\b\d[\d\s.\-]{6,}\d\b', '[TELEPHONE MASQUE]', text)
    # WhatsApp links (wa.me/...)
    text = re.sub(r'wa\.me/[\w+\-]+', '[CONTACT MASQUE]', text)
    # Telegram links (t.me/...)
    text = re.sub(r't\.me/[\w+\-]+', '[CONTACT MASQUE]', text)
    # Social media handles (@username)
    text = re.sub(r'@\w{2,}', '[CONTACT MASQUE]', text)
    # Instagram, WhatsApp, Telegram, etc. keywords
    text = re.sub(
        r'\b(?:insta(?:gram)?|whatsapp|telegram|snap(?:chat)?|facebook|fb|messenger)\b',
        '[CONTACT MASQUE]',
        text,
        flags=re.IGNORECASE,
    )
    return text
