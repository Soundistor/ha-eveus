"""Базовый класс для всех зарядок."""
from __future__ import annotations

import asyncio

import aiohttp

_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_TIMEOUT = aiohttp.ClientTimeout(total=10)

# The body /pageEvent returns when a write was applied. Confirmed live on
# firmware R3.05.4 (2026-07-27): every accepted write — currentSet, evseEnabled,
# aiMode — answers "OK". (Static firmware analysis had suggested
# "mainPost successfully"; that did not match the live device and made every
# accepted write look rejected — trust the live capture over the disassembly.)
# V1 answers differently and cannot be checked this way at all — see
# BaseCharger.write_ack.
_WRITE_OK = "OK"

AI_MODE_MAP = {0: "off", 1: "voltage", 2: "tesla_auto", 3: "power"}

# Below this the reading is the firmware's "sensor absent" sentinel (the
# station's own UI shows N/A), not a measurement — typically -60.
_TEMP_ABSENT_BELOW = -50


def blank_absent_temperature(value):
    """Return None for the 'no sensor' sentinel, the value itself otherwise."""
    try:
        return None if float(value) < _TEMP_ABSENT_BELOW else value
    except (ValueError, TypeError):
        return value


def as_enum_int(value):
    """int() for an enum code, or None when the raw value cannot be one.

    A numeric-but-unmapped code already folds to "unknown" through the maps'
    .get() fallback. Non-numeric garbage did not: it escaped transform_data and
    surfaced as a repair issue for the whole poll instead of one unknown sensor.

    TypeError matters most: a JSON null leaves raw.get("state", 0) as None (the
    default does not fire — the key is present) and int(None) raises TypeError,
    not ValueError. None is not a key in any map, so callers get "unknown" for
    free.
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


class BaseCharger:
    """Общая часть: запросы через общую сессию HA, базовый интерфейс.

    Сессию отдаёт Home Assistant (`async_get_clientsession`) — интеграция её не
    создаёт и не закрывает. `hass` необязателен: юнит-тесты `transform_data`
    инстанцируют зарядку без него и не делают сетевых запросов.
    """

    # Body a station returns when it applied a write, or None if this generation
    # gives no acknowledgement at all. Defaults to the V2 contract so a new,
    # unstudied generation fails loudly instead of silently skipping the check.
    write_ack: str | None = _WRITE_OK

    # Firmware version for generations that do not report one in /main; filled
    # in at setup by async_load_sw_version(), left as None where /main carries
    # it (V2's verFWMain).
    sw_version: str | None = None

    def __init__(self, ip: str, username: str | None = None,
                 password: str | None = None, hass=None) -> None:
        self.ip = ip
        self.auth = aiohttp.BasicAuth(username, password or "") if username else None
        self._hass = hass
        self._session: aiohttp.ClientSession | None = None
        # The station serves exactly ONE connection: a second one does not get
        # queued or refused, it CLOSES the existing session (seen client-side as
        # a sudden FIN/RST — ServerDisconnectedError, ConnectionResetError or a
        # truncated body). Every exchange with the device goes through this lock
        # so a write never overlaps a poll or another write.
        self._lock = asyncio.Lock()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            # Lazy import: keeps the module importable without homeassistant
            # (the charger package is loaded standalone in unit tests).
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            self._session = async_get_clientsession(self._hass)
        return self._session

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"http://{self.ip}{path}"
        async with self._lock, self._get_session().request(
            method, url, auth=self.auth, timeout=_TIMEOUT, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _request_text(self, method: str, path: str, **kwargs) -> str:
        url = f"http://{self.ip}{path}"
        async with self._lock, self._get_session().request(
            method, url, auth=self.auth, timeout=_TIMEOUT, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def _post_page_event(self, data: str) -> None:
        """Write one parameter and verify the station accepted it.

        /pageEvent never answers JSON: on V2 success is the plain text "OK" and
        a refusal is plain text too (ILLEGAL_CMD, "Failed to post control
        value", "content too long") — always with HTTP 200, so the body is the
        only signal we get. Generations that give no such signal set
        `write_ack = None` and are verified by HTTP status alone.
        """
        body = await self._request_text(
            "POST", "/pageEvent", data=data, headers=_FORM_HEADERS
        )
        if self.write_ack is not None and body.strip() != self.write_ack:
            # Lazy import: see _get_session.
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(
                f"Charger {self.ip} rejected '{data}': {body.strip()[:200]}"
            )

    async def get_status(self) -> dict:
        return await self._request("POST", "/main")

    async def async_load_sw_version(self) -> None:
        """Read the firmware version once at setup, where /main lacks one."""

    async def async_check_credentials(self) -> None:
        """Raise ClientResponseError(401) if the station rejects our credentials.

        Reading /main proves nothing about the password: POST handlers on this
        hardware check no authentication at all (firmware KB-01 §1.2, live on V1
        2026-07-30 and on V2 R3.05.4 2026-08-13 — a deliberately wrong password
        still returned 200 and a full JSON body). Only a generation whose
        auth-checking path has actually been measured overrides this; a probe
        that answered 401 to a VALID password would make the charger impossible
        to add at all, which is worse than not checking. Default: no check.
        """

    async def set_current(self, value: int) -> None:
        # The station range-checks nothing here: it truncates to a uint8_t and
        # keeps the result, so currentSet=999 was stored as 231 (999 & 0xFF) in
        # a live test. The `number` entity's min/max already guards its own
        # path; this catches the standalone service, which bypasses it.
        if not 0 <= value <= 255:
            # Lazy import: see _get_session.
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(
                f"Current {value} A is outside 0..255 — the charger would "
                "silently wrap it to a different value."
            )
        await self._post_page_event(f"currentSet={value:02d}")

    async def set_ai_mode(self, mode: int) -> None:
        # The station matches parameter names in the request body, so the write
        # is `aiMode` alone — same as the vendor's own web UI sends. The former
        # `pageevent=evseEnabled&` prefix was junk: no parameter of that name
        # exists, and the value it carried was the literal string "evseEnabled".
        # Read side stays `aiStatus`; that asymmetry is the station's, not ours.
        #
        # Same guard as set_current, for the same reason: the `select` entity's
        # options already bound this on its own path, so what is left is a direct
        # call from pyscript or custom code. V1 knows two modes, V2 four — the
        # valid set is the generation's, not the shared map's.
        if mode not in self.ai_modes.values():
            # Lazy import: see _get_session.
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError(
                f"AI mode {mode} is not one of {sorted(self.ai_modes.values())} "
                f"on {self.model_name}."
            )
        await self._post_page_event(f"aiMode={mode}")

    async def set_enabled(self, enabled: bool) -> None:
        raise NotImplementedError

    def transform_data(self, raw: dict) -> dict:
        return raw

    def is_charging_active(self, enabled_value) -> bool:
        raise NotImplementedError

    @property
    def min_current(self) -> int:
        raise NotImplementedError

    @property
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    def ai_modes(self) -> dict:
        raise NotImplementedError

    @property
    def capabilities(self) -> set:
        # Read without a guard by switch.py and button.py, so a generation that
        # forgets it fails at setup with AttributeError instead of saying what
        # is missing. sync_time is declared alongside for a complete contract —
        # it is only ever called when "sync_time" is in capabilities.
        raise NotImplementedError

    async def sync_time(self) -> None:
        raise NotImplementedError
