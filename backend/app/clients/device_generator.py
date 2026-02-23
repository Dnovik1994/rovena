import random

DESKTOP_DEVICES = [
    {"device_model": "PC 64bit", "system_version": "Linux 5.15"},
    {"device_model": "PC 64bit", "system_version": "Linux 6.1"},
    {"device_model": "PC 64bit", "system_version": "Linux 6.5"},
    {"device_model": "PC 64bit", "system_version": "Linux 6.6"},
    {"device_model": "PC 64bit", "system_version": "Linux 6.8"},
    {"device_model": "Ubuntu 22.04", "system_version": "Linux 5.15"},
    {"device_model": "Ubuntu 22.04", "system_version": "Linux 6.1"},
    {"device_model": "Ubuntu 24.04", "system_version": "Linux 6.8"},
    {"device_model": "Debian 12", "system_version": "Linux 6.1"},
    {"device_model": "Linux x86_64", "system_version": "Linux 6.5"},
    {"device_model": "Linux x86_64", "system_version": "Linux 6.6"},
]

APP_VERSIONS = ["4.11.7", "4.12.2", "4.14.4", "4.15.0", "4.16.6", "5.0.1", "5.1.5", "5.2.3"]

LANG_CODES = ["uk", "en", "pl", "de", "fr"]

LANG_MAP = {
    "uk": "uk_UA",
    "en": "en_US",
    "pl": "pl_PL",
    "de": "de_DE",
    "fr": "fr_FR",
}


def generate_device_config() -> dict:
    device = random.choice(DESKTOP_DEVICES)
    lang = random.choice(LANG_CODES)
    return {
        "device_model": device["device_model"],
        "system_version": device["system_version"],
        "app_version": random.choice(APP_VERSIONS),
        "lang_code": lang,
        "system_lang_code": LANG_MAP[lang],
    }
