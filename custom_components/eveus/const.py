DOMAIN = "eveus"

CONF_IP_ADDRESS = "ip_address"
CONF_MODEL = "model"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DEVICE_PREFIX = "device_prefix"

MODEL_V1 = "v1"
MODEL_V2 = "v2"

SUPPORTED_MODELS = {
    MODEL_V1: "Eveus API v1",
    MODEL_V2: "Eveus API v2",
}


def friendly_device_name(prefix: str, ip: str) -> str:
    """'eveus_home' -> 'Eveus Home'; empty prefix falls back to 'Eveus <ip>'."""
    if prefix:
        return prefix.replace("_", " ").title()
    return f"Eveus {ip}"
