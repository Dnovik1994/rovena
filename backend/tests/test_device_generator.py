from app.clients.device_generator import (
    ANDROID_SDK_VERSIONS,
    APP_VERSIONS,
    DEVICE_BRANDS,
    DEVICE_MODELS,
    LANG_CODES,
    SYSTEM_VERSIONS,
    generate_device_config,
)


def test_generate_device_config():
    config = generate_device_config()
    assert config["device_model"] in DEVICE_MODELS
    assert config["system_version"] in SYSTEM_VERSIONS
    assert config["app_version"] in APP_VERSIONS
    assert config["lang_code"] in LANG_CODES
    assert config["system_lang_code"] in LANG_CODES
    assert config["device_brand"] in DEVICE_BRANDS
    assert "app_build_id" in config

    if config["system_version"].startswith("Android"):
        assert config["android_sdk_version"] in ANDROID_SDK_VERSIONS
