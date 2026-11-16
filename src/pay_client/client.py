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

# Statuts d'un paiement qui n'est pas encore tranché.
EN_COURS = ("created", "pending")
# `?wait=` le plus long accepté par Pay (secondes).
ATTENTE_MAX = 25


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
        self,
        methode: str,
        chemin: str,
        corps: Any = None,
        *,
        cle_idempotence: str | None = None,
        delai: float | None = None,
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
                with urllib.request.urlopen(requete, timeout=delai or self.delai) as reponse:
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

    # ------------------------------------------------------------------ paiements
    def moyens(self, currency: str, amount: int) -> list[str]:
        """Les moyens payables maintenant pour ce montant (un fournisseur en panne n'y figure
        pas) : `["moov_money", "card", …]`."""
        requete = urllib.parse.urlencode({"currency": currency, "amount": amount})
        return [m["method"] for m in self._appel("GET", f"/v1/methods?{requete}")[1]["data"]]

    def creer_paiement(
        self,
        amount: int,
        currency: str,
        method: str,
        app_reference: str,
        *,
        phone: str | None = None,
        email: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        """Crée un paiement et le renvoie (`status`, `next_action` à montrer au payeur).

        `amount` : entier, dans la plus petite unité de la devise (5000 XOF, 2000 = 20,00 USD).
        `app_reference` : la commande. Si elle a déjà un paiement en cours ou encaissé, ce
        paiement-là est renvoyé tel quel (double clic, page rechargée) : aucun second paiement.
        Après un `failed` ou un `expired`, un nouvel appel crée un nouvel essai.
        """
        _entier(amount)
        corps: dict[str, Any] = {
            "amount": amount,
            "currency": currency,
            "method": method,
            "app_reference": app_reference,
        }
        client = {"phone": phone, "email": email}
        if any(client.values()):
            corps["customer"] = {k: v for k, v in client.items() if v}
        if description:
            corps["description"] = description
        if metadata:
            corps["metadata"] = metadata
        # Une clé neuve par appel : les relances de `_appel` la gardent (Pay rejoue sa
        # réponse), et l'unicité de `app_reference` chez Pay empêche tout doublon entre deux
        # appels.
        cle = f"pay:{app_reference}:{uuid.uuid4().hex}"
        try:
            return self._appel("POST", "/v1/payments", corps, cle_idempotence=cle)[1]
        except ErreurPay as erreur:
            details = erreur.details if isinstance(erreur.details, dict) else {}
            if erreur.code != "duplicate_app_reference" or not details.get("payment_id"):
                raise
            return self.lire_paiement(details["payment_id"])

    def lire_paiement(self, payment_id: str, *, attendre: int = 0) -> dict:
        """Lit un paiement. `attendre` (0 à 25 s) : Pay répond dès que le paiement quitte
        `created` / `pending`, ou au bout de ce délai."""
        chemin = f"/v1/payments/{urllib.parse.quote(payment_id)}"
        if attendre:
            chemin += f"?wait={int(attendre)}"
        # La réponse peut tarder `attendre` secondes, plus la relecture chez le fournisseur.
        return self._appel("GET", chemin, delai=self.delai + attendre)[1]

    def attendre_paiement(self, payment_id: str, *, delai_max: float = 120) -> dict:
        """Attend que le paiement quitte `created` / `pending` (au plus `delai_max` secondes)
        et le renvoie. Encore `pending` au retour : afficher « paiement en cours de
        vérification, vous serez prévenu » ; le signal `paiement_reussi` suivra.

        Sert à l'affichage. Le service vendu s'active sur le signal `paiement_reussi`."""
        echeance = time.monotonic() + delai_max
        while True:
            reste = round(echeance - time.monotonic())
            paiement = self.lire_paiement(payment_id, attendre=max(0, min(ATTENTE_MAX, reste)))
            if paiement["status"] not in EN_COURS or reste <= ATTENTE_MAX:
                return paiement

    def retrouver_paiements(self, app_reference: str) -> list[dict]:
        """Tous les essais de paiement d'une commande, le plus récent d'abord."""
        requete = urllib.parse.urlencode({"app_reference": app_reference})
        return self._appel("GET", f"/v1/payments?{requete}")[1]["data"]

    def confirmer_paiement(self, payment_id: str, otp: str | None = None) -> dict:
        """Envoie le code OTP saisi par le payeur (Orange), ou, sans code, encaisse un paiement
        PayPal approuvé. Code refusé : `ErreurPay` 422 (`invalid_otp`, `otp_expired`,
        `otp_amount_mismatch`) ; le paiement attend un nouveau code."""
        return self._appel(
            "POST",
            f"/v1/payments/{urllib.parse.quote(payment_id)}/confirm",
            {"otp": otp} if otp else {},
            cle_idempotence=f"confirm:{payment_id}:{uuid.uuid4().hex}",
        )[1]

    def annuler_paiement(self, payment_id: str) -> dict:
        """Annule un paiement encore en attente (`failed`, `failure.code` = `cancelled`)."""
        return self._appel(
            "POST",
            f"/v1/payments/{urllib.parse.quote(payment_id)}/cancel",
            {},
            cle_idempotence=f"cancel:{payment_id}",
        )[1]

    def rembourser(
        self, payment_id: str, amount: int | None = None, *, reference: str, reason: str = ""
    ) -> dict:
        """Rembourse tout (sans `amount`) ou partie d'un paiement encaissé, et renvoie le
        remboursement.

        `reference` : la référence de ce remboursement dans l'application (par exemple
        `avoir-17`). Rappeler avec la même référence ne rembourse pas deux fois."""
        corps: dict[str, Any] = {}
        if amount is not None:
            corps["amount"] = _entier(amount)
        if reason:
            corps["reason"] = reason
        return self._appel(
            "POST",
            f"/v1/payments/{urllib.parse.quote(payment_id)}/refunds",
            corps,
            cle_idempotence=f"refund:{payment_id}:{reference}",
        )[1]

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


def _entier(montant: Any) -> int:
    """Un montant : entier, dans la plus petite unité de la devise. Jamais de float."""
    if not isinstance(montant, int) or isinstance(montant, bool):
        raise TypeError("Montant : un entier, dans la plus petite unité de la devise.")
    return montant


def _json(octets: bytes) -> Any:
    try:
        return json.loads(octets or b"null")
    except ValueError:
        return None
