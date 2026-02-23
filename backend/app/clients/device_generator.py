import random

DEVICE_MODELS = [
    "PC 64bit",
    "Ubuntu 22.04",
    "Ubuntu 24.04",
    "Debian 12",
    "Linux x86_64",
]

SYSTEM_VERSIONS = [
    "Linux 5.15",
    "Linux 6.1",
    "Linux 6.5",
    "Linux 6.6",
    "Linux 6.8",
]

APP_VERSIONS = [
    "4.11.7",
    "4.12.2",
    "4.14.4",
    "4.15.0",
    "4.16.6",
    "5.0.1",
    "5.1.5",
    "5.2.3",
]

LANG_CODES = ["uk", "en", "pl", "de", "fr"]

SYSTEM_LANG_CODES = ["uk-UA", "en-US", "en-GB", "pl-PL", "de-DE", "fr-FR"]


def generate_device_config() -> dict[str, object]:
    lang_code = random.choice(LANG_CODES)
    lang_to_system = {
        "uk": "uk-UA",
        "en": random.choice(["en-US", "en-GB"]),
        "pl": "pl-PL",
        "de": "de-DE",
        "fr": "fr-FR",
    }
    return {
        "device_model": random.choice(DEVICE_MODELS),
        "system_version": random.choice(SYSTEM_VERSIONS),
        "app_version": random.choice(APP_VERSIONS),
        "lang_code": lang_code,
        "system_lang_code": lang_to_system[lang_code],
    }
