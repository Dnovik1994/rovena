from app.clients.device_generator import (
    APP_VERSIONS,
    DEVICE_MODELS,
    LANG_CODES,
    SYSTEM_LANG_CODES,
    SYSTEM_VERSIONS,
    generate_device_config,
)


def test_generate_device_config():
    config = generate_device_config()
    assert config["device_model"] in DEVICE_MODELS
    assert config["system_version"] in SYSTEM_VERSIONS
    assert config["app_version"] in APP_VERSIONS
    assert config["lang_code"] in LANG_CODES
    assert config["system_lang_code"] in SYSTEM_LANG_CODES


def test_no_mobile_fields():
    """Desktop config must not contain mobile-specific fields."""
    config = generate_device_config()
    assert "device_brand" not in config
    assert "android_sdk_version" not in config
    assert "app_build_id" not in config


def test_lang_code_consistency():
    """system_lang_code must match lang_code."""
    for _ in range(50):
        config = generate_device_config()
        lang = config["lang_code"]
        sys_lang = config["system_lang_code"]
        assert sys_lang.startswith(lang + "-") or (lang == "en" and sys_lang.startswith("en-"))
