import unicodedata

# Centroides approximatifs (lat, lon) de grandes villes françaises.
CITY_CENTROIDS: dict[str, tuple[float, float]] = {
    "paris": (48.8566, 2.3522),
    "marseille": (43.2965, 5.3698),
    "lyon": (45.7640, 4.8357),
    "toulouse": (43.6047, 1.4442),
    "nice": (43.7102, 7.2620),
    "nantes": (47.2184, -1.5536),
    "montpellier": (43.6108, 3.8767),
    "strasbourg": (48.5734, 7.7521),
    "bordeaux": (44.8378, -0.5792),
    "lille": (50.6292, 3.0573),
    "rennes": (48.1173, -1.6778),
    "reims": (49.2583, 4.0317),
    "toulon": (43.1242, 5.9280),
    "grenoble": (45.1885, 5.7245),
    "dijon": (47.3220, 5.0415),
    "angers": (47.4784, -0.5632),
    "nimes": (43.8367, 4.3601),
    "clermont-ferrand": (45.7772, 3.0870),
    "le havre": (49.4944, 0.1079),
    "rouen": (49.4432, 1.0993),
    "saint-etienne": (45.4397, 4.3872),
    "metz": (49.1193, 6.1757),
    "tours": (47.3941, 0.6848),
    "caen": (49.1829, -0.3707),
    "brest": (48.3904, -4.4861),
    "limoges": (45.8336, 1.2611),
    "perpignan": (42.6887, 2.8948),
    "poitiers": (46.5802, 0.3404),
    "ajaccio": (41.9192, 8.7386),
    "fort-de-france": (14.6161, -61.0588),
    "saint-denis": (48.9362, 2.3574),
    "nanterre": (48.8924, 2.2071),
}


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("’", "'").split())


def city_centroid(city: str) -> tuple[float, float] | None:
    return CITY_CENTROIDS.get(_norm(city))
