"""Client HTTP de l'API de Pay, sans dépendance (bibliothèque standard).

Seul le serveur de l'application l'utilise : la clé d'API ne va jamais dans un navigateur.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from . import __version__
from .gabarits import Gabarit

# Pauses avant chaque nouvel essai quand Pay est momentanément indisponible (même clé
# d'idempotence : aucun doublon possible).
RELANCES = (1.0, 3.0)


class ErreurPay(Exception):
    """Une réponse d'erreur de Pay (`{"error": {"code", "message", "retryable"}}`) ou une panne
    réseau (`code` = `network_error`, `status` = 0)."""

    def __init__(
        self, status: int, code: str, message: str, details: Any = None, retryable: bool = False
    ):
        super().__init__(f"{status} {code} : {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.retryable = retryable


def _reglage(nom: str) -> str:
    """Un réglage : Django s'il est configuré, sinon l'environnement."""
    try:
        from django.conf import settings

        if settings.configured and getattr(settings, nom, ""):
            return str(getattr(settings, nom))
    except ImportError:
        pass
    return os.environ.get(nom, "")


class Pay:
    def __init__(self, url: str | None = None, cle: str | None = None, *, delai: float = 30):
        self.url = (url or _reglage("PAY_URL")).rstrip("/")
        self.cle = cle or _reglage("PAY_API_KEY")
        self.delai = delai
        if not self.url or not self.cle:
            raise ValueError("PAY_URL et PAY_API_KEY sont obligatoires.")

    # ------------------------------------------------------------------ HTTP
    def _appel(
        self, methode: str, chemin: str, corps: Any = None, *, cle_idempotence: str | None = None
    ) -> tuple[int, Any]:
        donnees = None if corps is None else json.dumps(corps).encode()
        entetes = {
            "Authorization": f"Bearer {self.cle}",
            "Accept": "application/json",
            # Cloudflare refuse l'agent par défaut de urllib.
            "User-Agent": f"pay-client-python/{__version__}",
        }
        if donnees is not None:
            entetes["Content-Type"] = "application/json"
        if cle_idempotence:
            entetes["Idempotency-Key"] = cle_idempotence
        for essai in range(len(RELANCES) + 1):
            requete = urllib.request.Request(
                self.url + chemin, data=donnees, method=methode, headers=entetes
            )
            try:
                with urllib.request.urlopen(requete, timeout=self.delai) as reponse:
                    return reponse.status, json.loads(reponse.read() or b"null")
            except urllib.error.HTTPError as erreur:
                lu = _json(erreur.read())
                info = lu.get("error", {}) if isinstance(lu, dict) else {}
                exception = ErreurPay(
                    erreur.code,
                    info.get("code", "http_error"),
                    info.get("message", erreur.reason or ""),
                    info.get("details"),
                    bool(info.get("retryable")) or erreur.code in (502, 503, 504),
                )
            except (urllib.error.URLError, TimeoutError, ConnectionError) as erreur:
                exception = ErreurPay(0, "network_error", str(erreur), retryable=True)
            # Sans clé d'idempotence (GET, PUT), un nouvel essai est sans risque ; avec, Pay
            # rejoue la réponse d'origine.
            if not exception.retryable or essai == len(RELANCES):
                raise exception
            time.sleep(RELANCES[essai])
        raise AssertionError("inatteignable")

    # ------------------------------------------------------------------ messages
    def envoyer_message(
        self, to: str, gabarit: str, contexte: dict[str, Any] | None = None, *, reference: str
    ) -> dict:
        """Met un SMS en file chez Pay et renvoie le message (`status` : `queued`).

        `reference` : la référence de l'application, unique par message (100 caractères au
        plus). Renvoyer la même demande renvoie le même message, sans second SMS.
        """
        _, message = self._appel(
            "POST",
            "/v1/messages",
            {"to": to, "template": gabarit, "context": contexte or {}, "reference": reference},
            cle_idempotence=f"msg:{reference}",
        )
        return message

    def lire_message(self, message_id: str) -> dict:
        return self._appel("GET", f"/v1/messages/{urllib.parse.quote(message_id)}")[1]

    def apercu(self, gabarit: str, contexte: dict[str, Any] | None = None) -> dict:
        """Le texte final, son encodage et son nombre de segments, sans rien envoyer."""
        corps = {"template": gabarit, "context": contexte or {}}
        # Sans effet chez Pay : une clé neuve à chaque appel (jamais une réponse rejouée).
        return self._appel(
            "POST", "/v1/templates/preview", corps, cle_idempotence=f"apercu:{uuid.uuid4()}"
        )[1]

    def pousser_gabarit(self, gabarit: Gabarit) -> dict:
        """Déclare un gabarit chez Pay et le renvoie tel que Pay l'a gardé (`version` n'augmente
        que si le contenu a changé : pousser tous ses gabarits à chaque déploiement est sans
        risque)."""
        return self._appel(
            "PUT", f"/v1/templates/{urllib.parse.quote(gabarit.code)}", gabarit.corps()
        )[1]


def _json(octets: bytes) -> Any:
    try:
        return json.loads(octets or b"null")
    except ValueError:
        return None
