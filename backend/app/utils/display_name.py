from app.models.user import User


def get_display_name(user: User) -> str:
    """Get a display name for a user, preferring first/last name over email."""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    if user.first_name:
        return user.first_name
    return user.email.split("@")[0]
