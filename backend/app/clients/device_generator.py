import random
from uuid import uuid4

ANDROID_DEVICES = [
    # Samsung (7)
    {"device_model": "SM-G998B", "device_brand": "samsung", "system_version": "Android 14", "android_sdk_version": 34},
    {"device_model": "SM-S911B", "device_brand": "samsung", "system_version": "Android 14", "android_sdk_version": 34},
    {"device_model": "SM-S921B", "device_brand": "samsung", "system_version": "Android 14", "android_sdk_version": 34},
    {"device_model": "SM-S926B", "device_brand": "samsung", "system_version": "Android 13", "android_sdk_version": 33},
    {"device_model": "SM-A546B", "device_brand": "samsung", "system_version": "Android 13", "android_sdk_version": 33},
    {"device_model": "SM-G991B", "device_brand": "samsung", "system_version": "Android 12", "android_sdk_version": 31},
    {"device_model": "SM-A156B", "device_brand": "samsung", "system_version": "Android 12", "android_sdk_version": 31},
    # Google (4)
    {"device_model": "Pixel 7", "device_brand": "google", "system_version": "Android 13", "android_sdk_version": 33},
    {"device_model": "Pixel 7 Pro", "device_brand": "google", "system_version": "Android 13", "android_sdk_version": 33},
    {"device_model": "Pixel 8", "device_brand": "google", "system_version": "Android 14", "android_sdk_version": 34},
    {"device_model": "Pixel 8 Pro", "device_brand": "google", "system_version": "Android 14", "android_sdk_version": 34},
    # Xiaomi (4)
    {"device_model": "2201116SG", "device_brand": "xiaomi", "system_version": "Android 12", "android_sdk_version": 31},
    {"device_model": "23049RAD8C", "device_brand": "xiaomi", "system_version": "Android 14", "android_sdk_version": 34},
    {"device_model": "2211133G", "device_brand": "xiaomi", "system_version": "Android 13", "android_sdk_version": 33},
    {"device_model": "23078RKD5C", "device_brand": "xiaomi", "system_version": "Android 13", "android_sdk_version": 33},
    # OnePlus (3)
    {"device_model": "NE2215", "device_brand": "oneplus", "system_version": "Android 12", "android_sdk_version": 31},
    {"device_model": "CPH2449", "device_brand": "oneplus", "system_version": "Android 13", "android_sdk_version": 33},
    {"device_model": "CPH2573", "device_brand": "oneplus", "system_version": "Android 14", "android_sdk_version": 34},
    # Huawei (2)
    {"device_model": "VOG-L29", "device_brand": "huawei", "system_version": "Android 12", "android_sdk_version": 31},
    {"device_model": "LYA-L29", "device_brand": "huawei", "system_version": "Android 12", "android_sdk_version": 31},
]

IOS_DEVICES = [
    {"device_model": "iPhone13,2", "device_brand": "apple", "system_version": "iOS 16.7.1", "android_sdk_version": None},
    {"device_model": "iPhone13,4", "device_brand": "apple", "system_version": "iOS 16.7.1", "android_sdk_version": None},
    {"device_model": "iPhone14,5", "device_brand": "apple", "system_version": "iOS 17.2.1", "android_sdk_version": None},
    {"device_model": "iPhone14,7", "device_brand": "apple", "system_version": "iOS 17.2.1", "android_sdk_version": None},
    {"device_model": "iPhone14,8", "device_brand": "apple", "system_version": "iOS 17.4", "android_sdk_version": None},
    {"device_model": "iPhone15,2", "device_brand": "apple", "system_version": "iOS 17.4", "android_sdk_version": None},
    {"device_model": "iPhone15,3", "device_brand": "apple", "system_version": "iOS 17.5.1", "android_sdk_version": None},
    {"device_model": "iPhone15,4", "device_brand": "apple", "system_version": "iOS 17.5.1", "android_sdk_version": None},
    {"device_model": "iPhone16,1", "device_brand": "apple", "system_version": "iOS 17.5.1", "android_sdk_version": None},
    {"device_model": "iPhone16,2", "device_brand": "apple", "system_version": "iOS 17.4", "android_sdk_version": None},
]

ANDROID_APP_VERSIONS = ["10.14.5", "10.15.0", "11.0.0", "11.1.2", "11.2.0"]
IOS_APP_VERSIONS = ["10.3.1", "10.4.0", "10.5.0", "10.6.0", "10.6.3"]

LANG_CODES = ["en", "uk", "ru", "de", "pl", "fr", "es", "pt", "it"]
SYSTEM_LANG_CODES = ["en-US", "uk-UA", "ru-RU", "de-DE", "pl-PL", "fr-FR", "es-ES"]


def generate_device_config() -> dict[str, object]:
    if random.random() < 0.7:
        device = random.choice(ANDROID_DEVICES)
        app_version = random.choice(ANDROID_APP_VERSIONS)
    else:
        device = random.choice(IOS_DEVICES)
        app_version = random.choice(IOS_APP_VERSIONS)

    return {
        "device_model": device["device_model"],
        "device_brand": device["device_brand"],
        "system_version": device["system_version"],
        "android_sdk_version": device["android_sdk_version"],
        "app_version": app_version,
        "lang_code": random.choice(LANG_CODES),
        "system_lang_code": random.choice(SYSTEM_LANG_CODES),
        "app_build_id": uuid4().hex[:8],
    }
