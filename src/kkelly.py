"""
Kenny Football v3.0 — Kelly fractionnaire pur.

Formule :
    f* = (proba × cote - 1) / (cote - 1)
    mise = bankroll × f* × fraction
    mise = min(mise, cap)

Fraction recommandée : 0.25 (Kelly /4).
Plafonds : strong 15€ / medium 10€ / weak 5€.
"""

from __future__ import annotations


KELLY_FRACTION = 0.25
CAPS = {
    "strong": 15.0,
    "medium": 10.0,
    "weak": 0.0,  # Exclu (52.4% réussite, break-even)
    "weak_nocote": 0.0,  # Ancien moteur ne pariant PAS sur weak_nocote
    "medium_nocote": 2.0,
    "low_edge": 0.0,   # NOUVEAU : marché valide mais edge insuffisant
    "rejected": 0.0,
}


def kelly_mise(
    proba: float,
    cote: float | None,
    signal: str,
    bankroll: float = 1000.0,
    fraction: float = KELLY_FRACTION,
) -> float:
    """
    Retourne la mise (€) pour un pari, selon la formule de Kelly fractionnaire.
    Si `cote` est None (nocote), retourne la mise plancher du signal.
    """
    cap = CAPS.get(signal, 5.0)

    if signal in ("weak_nocote", "medium_nocote"):
        return min(CAPS[signal], cap)

    if signal == "rejected":
        return 0.0

    if cote is None or cote <= 1.0:
        return 0.0

    if proba is None or proba <= 0.0 or proba >= 1.0:
        return 0.0

    edge = proba * cote - 1.0
    if edge <= 0.0:
        return 0.0

    kelly_full = edge / (cote - 1.0)
    mise = bankroll * kelly_full * fraction
    mise = max(0.0, min(mise, cap))
    return round(mise, 2)


def kelly_implied_proba(cote: float) -> float:
    """Proba implicite d'une cote (avec marge)."""
    if cote is None or cote <= 1.0:
        return 0.0
    return 1.0 / cote


def kelly_edge(proba: float, cote: float | None) -> float | None:
    if cote is None or cote <= 1.0:
        return None
    return round(proba * cote - 1.0, 4)
