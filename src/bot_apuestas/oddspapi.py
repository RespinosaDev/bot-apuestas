"""Cliente mínimo de OddsPapi v4 con pausas por endpoint y reintentos ante HTTP 429."""

from __future__ import annotations

import time

import httpx

BASE_URL = "https://api.oddspapi.io/v4"

# Pausa mínima entre llamadas a cada endpoint (documentación de OddsPapi), con margen.
COOLDOWN_S = {
    "historical-odds": 5.5,
    "fixtures": 2.5,
    "odds-by-tournaments": 2.5,
    "settlements": 2.5,
    "scores": 1.5,
    "participants": 1.5,
}
DEFAULT_COOLDOWN_S = 2.5


class OddsPapiClient:
    def __init__(self, api_key: str, timeout: float = 120):
        self._key = api_key
        self._http = httpx.Client(timeout=timeout)
        self._last_call: dict[str, float] = {}

    def get(self, endpoint: str, **params) -> object:
        cooldown = COOLDOWN_S.get(endpoint, DEFAULT_COOLDOWN_S)
        for attempt in range(5):
            wait = self._last_call.get(endpoint, 0) + cooldown - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call[endpoint] = time.monotonic()
            try:
                r = self._http.get(
                    f"{BASE_URL}/{endpoint}", params={"apiKey": self._key, **params}
                )
            except httpx.TransportError:  # conexión cortada, timeout...
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(cooldown * (attempt + 1))
                continue
            if r.status_code == 404:  # p. ej. partido sin histórico
                return None
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"{endpoint}: 5 intentos fallidos seguidos")

    def close(self) -> None:
        self._http.close()
