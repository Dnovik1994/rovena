import random
import secrets

DEVICE_MODELS = ["SM-G998B", "Pixel 7", "iPhone14,5", "Redmi Note 12", "OnePlus 11", "Galaxy S23"]
SYSTEM_VERSIONS = ["Android 14", "Android 13", "iOS 17.0", "Android 12"]
APP_VERSIONS = ["10.14.5", "10.15.0", "11.0.0", "9.12.3"]
LANG_CODES = ["en", "ru", "uk", "de", "fr"]
DEVICE_BRANDS = ["samsung", "google", "apple", "xiaomi", "oneplus"]
ANDROID_SDK_VERSIONS = [33, 31, 34, 30]


def generate_device_config() -> dict[str, object]:
    system_version = random.choice(SYSTEM_VERSIONS)
    device_model = random.choice(DEVICE_MODELS)
    app_version = random.choice(APP_VERSIONS)
    lang_code = random.choice(LANG_CODES)
    system_lang_code = random.choice(LANG_CODES)
    device_brand = random.choice(DEVICE_BRANDS)
    app_build_id = secrets.token_hex(4)

    device_config: dict[str, object] = {
        "device_model": device_model,
        "system_version": system_version,
        "app_version": app_version,
        "lang_code": lang_code,
        "system_lang_code": system_lang_code,
        "device_brand": device_brand,
        "app_build_id": app_build_id,
    }

    if system_version.startswith("Android"):
        device_config["android_sdk_version"] = random.choice(ANDROID_SDK_VERSIONS)

    return device_config
