"""Create an admin user in the eMecano database.

Usage:
    python scripts/create_admin.py admin@emecano.fr password123
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import hash_password
from app.database import async_session
from app.models.enums import UserRole
from app.models.user import User


async def create_admin(email: str, password: str) -> None:
    """Create an admin user with the given email and password."""
    async with async_session() as db:
        # Check if user already exists
        result = await db.execute(select(User).where(User.email == email))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Error: User with email '{email}' already exists.")
            sys.exit(1)

        user = User(
            email=email,
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
            is_verified=True,
        )
        db.add(user)
        await db.commit()

        print(f"Admin user created successfully: {email} (id={user.id})")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python scripts/create_admin.py <email> <password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    asyncio.run(create_admin(email, password))


if __name__ == "__main__":
    main()
