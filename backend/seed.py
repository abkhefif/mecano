"""Seed script for eMecano backend.

Creates baseline data for testing:
- 1 admin user
- 2 verified mechanics with profiles and availabilities
- 2 verified buyers

Idempotent: checks if users exist before creating them.
Run with: python seed.py

R-005: Passwords are read from environment variables with dev-only fallbacks.
Set SEED_ADMIN_PASSWORD / SEED_USER_PASSWORD in your environment for non-default values.
"""

import asyncio
import os
import sys
import uuid
from datetime import date, time, timedelta

from app.config import settings

# Guard: prevent running on production
if settings.APP_ENV == "production":
    print("ERROR: Cannot seed production database.")
    sys.exit(1)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import hash_password
from app.database import async_session, engine, Base
from app.models.availability import Availability
from app.models.enums import UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User


# R-005: Read seed passwords from env vars with dev-only fallbacks
SEED_ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "Admin123!")
SEED_USER_PASSWORD = os.environ.get("SEED_USER_PASSWORD", "Test1234!")

SEED_USERS = [
    {
        "email": "admin@emecano.fr",
        "password": SEED_ADMIN_PASSWORD,
        "role": UserRole.ADMIN,
        "first_name": "Admin",
        "last_name": "eMecano",
        "phone": "+33600000000",
        "is_verified": True,
    },
    {
        "email": "mechanic1@emecano.fr",
        "password": SEED_USER_PASSWORD,
        "role": UserRole.MECHANIC,
        "first_name": "Jean",
        "last_name": "Dupont",
        "phone": "+33600000001",
        "is_verified": True,
    },
    {
        "email": "mechanic2@emecano.fr",
        "password": SEED_USER_PASSWORD,
        "role": UserRole.MECHANIC,
        "first_name": "Pierre",
        "last_name": "Martin",
        "phone": "+33600000002",
        "is_verified": True,
    },
    {
        "email": "buyer1@emecano.fr",
        "password": SEED_USER_PASSWORD,
        "role": UserRole.BUYER,
        "first_name": "Marie",
        "last_name": "Leclerc",
        "phone": "+33600000003",
        "is_verified": True,
    },
    {
        "email": "buyer2@emecano.fr",
        "password": SEED_USER_PASSWORD,
        "role": UserRole.BUYER,
        "first_name": "Sophie",
        "last_name": "Bernard",
        "phone": "+33600000004",
        "is_verified": True,
    },
]


MECHANIC_PROFILES = [
    {
        "email": "mechanic1@emecano.fr",
        "city": "Toulouse",
        "city_lat": 43.6047,
        "city_lng": 1.4442,
        "max_radius_km": 30,
        "free_zone_km": 10,
        "accepted_vehicle_types": ["car", "motorcycle"],
        "is_identity_verified": True,
        "is_active": True,
        "has_obd_diagnostic": True,
    },
    {
        "email": "mechanic2@emecano.fr",
        "city": "Paris",
        "city_lat": 48.8566,
        "city_lng": 2.3522,
        "max_radius_km": 20,
        "free_zone_km": 5,
        "accepted_vehicle_types": ["car", "utility"],
        "is_identity_verified": True,
        "is_active": True,
        "has_obd_diagnostic": False,
    },
]


async def seed() -> None:
    async with async_session() as db:
        user_map: dict[str, User] = {}

        # Create users (idempotent)
        for user_data in SEED_USERS:
            result = await db.execute(
                select(User).where(User.email == user_data["email"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"  [skip] User {user_data['email']} already exists")
                user_map[user_data["email"]] = existing
                continue

            user = User(
                id=uuid.uuid4(),
                email=user_data["email"],
                password_hash=hash_password(user_data["password"]),
                role=user_data["role"],
                first_name=user_data["first_name"],
                last_name=user_data["last_name"],
                phone=user_data["phone"],
                is_verified=user_data["is_verified"],
            )
            db.add(user)
            await db.flush()
            user_map[user_data["email"]] = user
            print(f"  [created] User {user_data['email']} ({user_data['role'].value})")

        # Create mechanic profiles (idempotent)
        for profile_data in MECHANIC_PROFILES:
            user = user_map[profile_data["email"]]
            result = await db.execute(
                select(MechanicProfile).where(MechanicProfile.user_id == user.id)
            )
            existing_profile = result.scalar_one_or_none()
            if existing_profile:
                print(f"  [skip] Profile for {profile_data['email']} already exists")
                profile = existing_profile
            else:
                profile = MechanicProfile(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    city=profile_data["city"],
                    city_lat=profile_data["city_lat"],
                    city_lng=profile_data["city_lng"],
                    max_radius_km=profile_data["max_radius_km"],
                    free_zone_km=profile_data["free_zone_km"],
                    accepted_vehicle_types=profile_data["accepted_vehicle_types"],
                    is_identity_verified=profile_data["is_identity_verified"],
                    is_active=profile_data["is_active"],
                    has_obd_diagnostic=profile_data["has_obd_diagnostic"],
                )
                db.add(profile)
                await db.flush()
                print(f"  [created] MechanicProfile for {profile_data['email']} in {profile_data['city']}")

            # Create availability slots for the next 7 days (idempotent)
            tomorrow = date.today() + timedelta(days=1)
            for day_offset in range(7):
                slot_date = tomorrow + timedelta(days=day_offset)
                result = await db.execute(
                    select(Availability).where(
                        Availability.mechanic_id == profile.id,
                        Availability.date == slot_date,
                    )
                )
                if result.scalars().first():
                    continue  # slots already exist for this date

                # Morning slots: 09:00-12:00
                avail_am = Availability(
                    id=uuid.uuid4(),
                    mechanic_id=profile.id,
                    date=slot_date,
                    start_time=time(9, 0),
                    end_time=time(12, 0),
                    is_booked=False,
                )
                db.add(avail_am)

                # Afternoon slots: 14:00-17:00
                avail_pm = Availability(
                    id=uuid.uuid4(),
                    mechanic_id=profile.id,
                    date=slot_date,
                    start_time=time(14, 0),
                    end_time=time(17, 0),
                    is_booked=False,
                )
                db.add(avail_pm)

            await db.flush()
            print(f"  [created] Availability slots for {profile_data['email']} (next 7 days)")

        await db.commit()
        print("\nSeed completed successfully.")


if __name__ == "__main__":
    print("Seeding eMecano database...")
    asyncio.run(seed())
