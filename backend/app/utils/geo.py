from geopy.distance import geodesic


def calculate_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate geodesic distance in km between two coordinate pairs."""
    return geodesic((lat1, lng1), (lat2, lng2)).km
