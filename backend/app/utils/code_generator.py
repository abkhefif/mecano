import secrets


def generate_check_in_code() -> str:
    """Generate a random 4-digit code for check-in validation."""
    return f"{secrets.randbelow(10000):04d}"
