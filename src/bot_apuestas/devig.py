"""Cálculo de cuota justa (quitar el margen de la casa) y del edge de una cuota."""

from __future__ import annotations


def fair_prices_multiplicative(prices: list[float]) -> list[float]:
    """Devig multiplicativo: reparte el margen en proporción a la probabilidad implícita."""
    implied = [1 / p for p in prices]
    total = sum(implied)
    return [total / i for i in implied]


def fair_prices_power(prices: list[float], tol: float = 1e-10) -> list[float]:
    """Devig "power": prob_i = (1/p_i)^k con k tal que sumen 1.

    Carga más margen en las cuotas altas (sesgo favorito-longshot), así que es más
    conservador que el multiplicativo al evaluar cuotas altas.
    """
    implied = [1 / p for p in prices]
    if sum(implied) <= 1:
        return list(prices)
    lo, hi = 1.0, 10.0
    while hi - lo > tol:
        k = (lo + hi) / 2
        if sum(q**k for q in implied) > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return [1 / q**k for q in implied]


def edge(price: float, fair_price: float) -> float:
    """Valor esperado por unidad apostada si fair_price es la cuota justa: price/fair - 1."""
    return price / fair_price - 1
