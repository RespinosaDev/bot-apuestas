"""Alertas por Telegram (API HTTP directa). Sin token configurado, las alertas salen por consola."""

from __future__ import annotations

import html
from zoneinfo import ZoneInfo

import httpx

from bot_apuestas.catalog import selection_label
from bot_apuestas.detector import LiveSurebet, ValueBet

MADRID = ZoneInfo("Europe/Madrid")
TOURNAMENT_NAMES = {8: "LaLiga", 17: "Premier League"}
DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _when(fx) -> str:
    local = fx.start.astimezone(MADRID)
    return f"{DAYS[local.weekday()]} {local:%d/%m %H:%M}"


def format_alert(vb: ValueBet, stake_eur: float) -> str:
    fx = vb.fixture
    start = _when(fx)
    e = html.escape
    lines = [
        (f"<b>VALUE BET</b> · <b>{e(vb.bookmaker)}</b> · edge <b>{vb.edge * 100:+.1f} %</b> "
        f"(conservador {vb.edge_power * 100:+.1f} %)"),
        f"{e(fx.home)} - {e(fx.away)} ({e(TOURNAMENT_NAMES.get(fx.tournament_id, ''))})",
        f"{start} · faltan {vb.hours_to_kickoff:.0f} h",
        f"<b>{e(selection_label(vb.market, vb.outcome_id, fx.home, fx.away))}</b> @ <b>{vb.price:.2f}</b>",
        f"Cuota justa Pinnacle: {vb.fair:.2f} (límite {vb.ref_limit or '?'})",
        f"Stake sugerido: {stake_eur:g} € · apuesta solo si la cuota sigue ≥ {vb.fair * 1.02:.2f}",
    ]
    if vb.quote_age_h is not None and vb.quote_age_h >= 24:
        lines.append(f"Aviso: cuota sin cambios desde hace {vb.quote_age_h / 24:.0f} días: puede estar desfasada")
    if vb.market_flagged:
        lines.append("Aviso: OddsPapi marca este mercado como inactivo: comprueba que está en la web")
    if link := fx.links.get(vb.bookmaker):
        lines.append(e(link))
    return "\n".join(lines)


def format_surebet(sb: LiveSurebet, total_eur: float) -> str:
    fx = sb.fixture
    e = html.escape
    stakes = sb.stakes(total_eur)
    payout = sb.payout(total_eur)
    lines = [
        f"<b>SUREBET +{sb.profit * 100:.2f} %</b> garantizado",
        f"{e(fx.home)} - {e(fx.away)} ({e(TOURNAMENT_NAMES.get(fx.tournament_id, ''))})",
        f"{_when(fx)} · faltan {sb.hours_to_kickoff:.0f} h",
        "",
    ]
    for oid, (book, price) in sorted(sb.legs.items(), key=lambda kv: kv[1][1], reverse=True):
        label = selection_label(sb.market, oid, fx.home, fx.away)
        lines.append(f"• <b>{e(label)}</b> @ <b>{price:.2f}</b> en <b>{e(book)}</b> → "
                     f"apostar <b>{stakes[oid]:.2f} €</b>")
        if link := fx.links.get(book):
            lines.append(f"  {e(link)}")
    lines += [
        "",
        (f"Total {total_eur:g} € → cobras <b>{payout:.2f} €</b> pase lo que pase "
        f"(<b>+{payout - total_eur:.2f} €</b>)"),
        ("Antes de apostar, comprueba TODAS las cuotas. Empieza por la cuota más alta "
        "(la que antes suele cambiar); si alguna ha bajado, no sigas."),
    ]
    if sb.flagged_books:
        lines.append("Aviso: OddsPapi marca el mercado como inactivo en: "
                     + e(", ".join(sorted(sb.flagged_books))))
    return "\n".join(lines)


class Notifier:
    def __init__(self, token: str | None, chat_id: str | None):
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            print("\n[ALERTA]\n" + text.replace("<b>", "").replace("</b>", ""))
            return
        r = httpx.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        r.raise_for_status()


def find_chat_ids(token: str) -> list[tuple[str, str]]:
    """Chats que han escrito al bot (para obtener TELEGRAM_CHAT_ID)."""
    r = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    r.raise_for_status()
    chats = {}
    for upd in r.json().get("result", []):
        chat = (upd.get("message") or {}).get("chat") or {}
        if chat:
            chats[str(chat["id"])] = chat.get("first_name") or chat.get("title") or ""
    return list(chats.items())
