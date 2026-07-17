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


EVENT_CHARGING_STARTED = "eveus_charging_started"
EVENT_SESSION_ENDED = "eveus_session_ended"

SESSION_ACTIVE_STATES = frozenset({"charging", "paused"})


def session_transition(prev_state: str, new_state: str) -> str | None:
    """Classify a state change into a session lifecycle event, or None.

    'charging_started' fires on entering 'charging' (including resume from
    'paused'); 'session_ended' fires on leaving the active set
    ({'charging', 'paused'}). Internal charging<->paused moves and
    idle<->idle changes return None.
    """
    if new_state == "charging" and prev_state != "charging":
        return "charging_started"
    if prev_state in SESSION_ACTIVE_STATES and new_state not in SESSION_ACTIVE_STATES:
        return "session_ended"
    return None
