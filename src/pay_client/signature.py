"""Vérification des notifications de Pay (en-tête `X-Signature: t=…,v1=…[,v1=…]`)."""

from __future__ import annotations

import hashlib
import hmac
import time

TOLERANCE_S = 300


def signature_valide(
    secret: str,
    corps: bytes,
    entete: str,
    *,
    maintenant: float | None = None,
    tolerance: int = TOLERANCE_S,
) -> bool:
    """`corps` : les octets bruts reçus, avant tout décodage. Toutes les `v1` sont essayées : il
    y en a deux pendant les 24 h d'une rotation du secret."""
    if not secret or not entete:
        return False
    try:
        paires = [p.strip().split("=", 1) for p in entete.split(",") if "=" in p]
        t = int(next(v for k, v in paires if k == "t"))
    except (StopIteration, ValueError):
        return False
    if abs((time.time() if maintenant is None else maintenant) - t) > tolerance:
        return False
    attendu = hmac.new(secret.encode(), f"{t}.".encode() + corps, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(attendu, v) for k, v in paires if k == "v1")


def signer(secret: str, corps: bytes, t: int | None = None) -> str:
    """L'en-tête que Pay enverrait : pour les tests de l'application."""
    t = int(time.time()) if t is None else t
    v1 = hmac.new(secret.encode(), f"{t}.".encode() + corps, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"
