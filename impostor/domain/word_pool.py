import secrets

WORDS = [
    "apple",
    "river",
    "castle",
    "forest",
    "banana",
    "mountain",
    "desert",
    "ocean",
    "piano",
    "rocket",
    "garden",
    "island",
]


def pick_secret_word() -> str:
    return secrets.choice(WORDS)
