from app.clients.device_generator import (
    ANDROID_APP_VERSIONS,
    ANDROID_DEVICES,
    IOS_APP_VERSIONS,
    IOS_DEVICES,
    LANG_CODES,
    SYSTEM_LANG_CODES,
    generate_device_config,
)

ALL_DEVICES = ANDROID_DEVICES + IOS_DEVICES
ALL_DEVICE_MODELS = [d["device_model"] for d in ALL_DEVICES]
ALL_DEVICE_BRANDS = [d["device_brand"] for d in ALL_DEVICES]
ALL_SYSTEM_VERSIONS = [d["system_version"] for d in ALL_DEVICES]
ALL_APP_VERSIONS = ANDROID_APP_VERSIONS + IOS_APP_VERSIONS
ANDROID_SDK_VERSIONS = [d["android_sdk_version"] for d in ANDROID_DEVICES]


def test_generate_device_config():
    config = generate_device_config()
    assert config["device_model"] in ALL_DEVICE_MODELS
    assert config["system_version"] in ALL_SYSTEM_VERSIONS
    assert config["app_version"] in ALL_APP_VERSIONS
    assert config["lang_code"] in LANG_CODES
    assert config["system_lang_code"] in SYSTEM_LANG_CODES
    assert config["device_brand"] in ALL_DEVICE_BRANDS
    assert "app_build_id" in config

    if config["system_version"].startswith("Android"):
        assert config["android_sdk_version"] in ANDROID_SDK_VERSIONS
    else:
        assert config["android_sdk_version"] is None
