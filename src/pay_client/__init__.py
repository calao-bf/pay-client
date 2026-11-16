"""Client de Pay, l'orchestrateur de paiement et de messages du parc Calao.

Réglages (Django ou variables d'environnement) : `PAY_URL`, `PAY_API_KEY` et, pour recevoir les
notifications, `PAY_WEBHOOK_SECRET`.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .client import ErreurPay, Pay  # noqa: E402
from .gabarits import Gabarit  # noqa: E402
from .signature import signature_valide, signer  # noqa: E402

_defaut: Pay | None = None


def pay() -> Pay:
    """Le client configuré par les réglages, créé au premier appel."""
    global _defaut
    if _defaut is None:
        _defaut = Pay()
    return _defaut


def envoyer_sms(to: str, gabarit: str, contexte: dict | None = None, *, reference: str) -> dict:
    """Raccourci : `pay().envoyer_message(...)`."""
    return pay().envoyer_message(to, gabarit, contexte, reference=reference)


__all__ = [
    "ErreurPay",
    "Gabarit",
    "Pay",
    "envoyer_sms",
    "pay",
    "signature_valide",
    "signer",
]
