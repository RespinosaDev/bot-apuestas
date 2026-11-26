"""Configuración del bot, leída de variables de entorno (.env). Valores por defecto = Fase 0.5."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Config:
    oddspapi_key: str
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    reference: str = "pinnacle"
    books: list[str] = field(default_factory=lambda: ["winamax.es", "codere.es", "bet365.es"])
    tournaments: list[int] = field(default_factory=lambda: [8, 17])  # LaLiga, Premier League
    min_edge: float = 0.03
    max_edge: float = 0.30  # por encima: probable error de datos
    min_hours: float = 0.0
    max_hours: float = 72.0  # con más antelación el estudio dio CLV ~0
    max_market_age_h: float = 24.0  # mercado sin cambios en más tiempo = probablemente desfasado
    poll_minutes: int = 30
    active_hours: tuple[int, int] = (8, 23)  # hora de Madrid [inicio, fin)
    stake_eur: float = 10.0
    # Surebets: casas donde buscarlas (lista vacía = desactivadas), umbrales y total a repartir.
    surebet_books: list[str] = field(default_factory=lambda: [
        "winamax.es", "codere.es", "bet365.es", "betway.es", "bwin.es"])
    surebet_min_profit: float = 0.005
    surebet_max_profit: float = 0.10  # por encima: probable error de datos
    surebet_stake_eur: float = 100.0
    request_reserve: int = 10  # peticiones que no se gastan nunca
    db_path: Path = RAIZ / "data" / "bot.sqlite"
    cache_dir: Path = RAIZ / "data" / "cache"
    muestra_path: Path = RAIZ / "docs" / "prueba_alertas.csv"  # prueba de disponibilidad

    @property
    def all_books(self) -> list[str]:
        """Casas a descargar: las de value bets más las de surebets, sin repetir."""
        return list(dict.fromkeys([*self.books, *self.surebet_books]))

    @property
    def requests_per_poll(self) -> int:
        return 1 + len(self.all_books)


def load_config() -> Config:
    load_dotenv(RAIZ / ".env")
    key = os.getenv("ODDSPAPI_KEY")
    if not key:
        raise SystemExit("Falta ODDSPAPI_KEY en .env")
    cfg = Config(
        oddspapi_key=key,
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
    )
    if v := os.getenv("BOT_REFERENCE"):
        cfg.reference = v
    if v := os.getenv("BOT_BOOKS"):
        cfg.books = _list(v)
    if v := os.getenv("BOT_TOURNAMENTS"):
        cfg.tournaments = [int(t) for t in _list(v)]
    if v := os.getenv("BOT_MIN_EDGE"):
        cfg.min_edge = float(v)
    if v := os.getenv("BOT_MAX_HOURS"):
        cfg.max_hours = float(v)
    if v := os.getenv("BOT_MAX_MARKET_AGE_H"):
        cfg.max_market_age_h = float(v)
    if v := os.getenv("BOT_POLL_MINUTES"):
        cfg.poll_minutes = int(v)
    if v := os.getenv("BOT_ACTIVE_HOURS"):
        start, end = v.split("-")
        cfg.active_hours = (int(start), int(end))
    if v := os.getenv("BOT_STAKE_EUR"):
        cfg.stake_eur = float(v)
    if (v := os.getenv("BOT_SUREBET_BOOKS")) is not None:
        cfg.surebet_books = _list(v)  # vacío = sin surebets
    if v := os.getenv("BOT_SUREBET_MIN_PROFIT"):
        cfg.surebet_min_profit = float(v)
    if v := os.getenv("BOT_SUREBET_STAKE_EUR"):
        cfg.surebet_stake_eur = float(v)
    return cfg
