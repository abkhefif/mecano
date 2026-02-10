from geopy.distance import geodesic

# Common cities in Occitanie with their coordinates (for MVP)
CITY_COORDS: dict[str, tuple[float, float]] = {
    "toulouse": (43.6047, 1.4442),
    "montpellier": (43.6108, 3.8767),
    "nimes": (43.8367, 4.3601),
    "perpignan": (42.6986, 2.8956),
    "beziers": (43.3440, 3.2191),
    "narbonne": (43.1840, 2.9990),
    "carcassonne": (43.2130, 2.3491),
    "albi": (43.9277, 2.1484),
    "tarbes": (43.2329, 0.0782),
    "auch": (43.6458, 0.5860),
    "rodez": (44.3496, 2.5752),
    "cahors": (44.4494, 1.4402),
    "foix": (42.9649, 1.6053),
    "mende": (44.5181, 3.4986),
    "castres": (43.6000, 2.2500),
    "sete": (43.4075, 3.6967),
    "muret": (43.4619, 1.3267),
    "blagnac": (43.6392, 1.3939),
    "colomiers": (43.6119, 1.3350),
    "tournefeuille": (43.5833, 1.3500),
}


def calculate_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate geodesic distance in km between two coordinate pairs."""
    return geodesic((lat1, lng1), (lat2, lng2)).km


def get_city_coords(city_name: str) -> tuple[float, float] | None:
    """Look up coordinates for a known city name (case-insensitive)."""
    return CITY_COORDS.get(city_name.lower().strip())
