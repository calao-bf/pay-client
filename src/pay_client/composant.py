"""Le composant de paiement intégré à la page : les adresses que son JavaScript appelle.

Le navigateur ne parle qu'au serveur de l'application ; ces vues appellent Pay avec la clé
d'API, qui ne quitte jamais le serveur. Le montant, la devise et la référence viennent toujours
du serveur, par la fonction du réglage `PAY_COMMANDE` :

    # settings.py
    PAY_COMMANDE = "boutique.paiements.commande_a_payer"

    # boutique/paiements.py
    def commande_a_payer(request, commande):
        cmd = get_object_or_404(Commande, pk=commande, client=request.user)  # 404 sinon
        return {"amount": cmd.total, "currency": "XOF", "app_reference": f"commande-{cmd.pk}"}

Clés facultatives du dictionnaire : `description`, `email`, `phone` (proposé dans le champ du
téléphone), `metadata`. La page n'envoie que le moyen choisi et le téléphone du payeur.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404, HttpRequest, JsonResponse
from django.utils.module_loading import import_string
from django.views.decorators.http import require_GET, require_POST

from . import pay
from .client import ATTENTE_MAX, EN_COURS, ErreurPay

# Ce que la page reçoit d'un paiement : rien d'autre (ni métadonnées ni référence).
CHAMPS_PUBLICS = (
    "id",
    "status",
    "amount",
    "currency",
    "method",
    "next_action",
    "failure",
    "livemode",
)
# Un paiement qui occupe déjà la commande : la page le reprend au lieu d'en proposer un autre.
OCCUPANTS = (*EN_COURS, "succeeded", "partially_refunded", "refunded")


def _commande(request: HttpRequest, commande: str) -> dict[str, Any]:
    chemin = getattr(settings, "PAY_COMMANDE", "")
    if not chemin:
        raise ImproperlyConfigured("PAY_COMMANDE : la fonction qui décrit la commande à payer.")
    donnees = import_string(chemin)(request, commande)
    if not donnees:
        raise Http404
    return donnees


def _public(paiement: dict) -> dict:
    return {cle: paiement.get(cle) for cle in CHAMPS_PUBLICS}


def _erreur(erreur: ErreurPay) -> JsonResponse:
    # Une erreur de la demande (400, 409, 422) est rendue telle quelle à la page ; une panne
    # de Pay ou du réseau devient un 502.
    statut = erreur.status if 400 <= erreur.status < 500 else 502
    corps = {"error": {"code": erreur.code, "message": erreur.message}}
    return JsonResponse(corps, status=statut)


def _corps(request: HttpRequest) -> dict:
    try:
        lu = json.loads(request.body or b"{}")
    except ValueError:
        lu = None
    return lu if isinstance(lu, dict) else {}


def _paiement_de(commande: dict, paiement: dict) -> dict:
    """Le paiement, seulement s'il appartient à cette commande (sinon 404)."""
    if paiement.get("app_reference") != commande["app_reference"]:
        raise Http404
    return paiement


@require_GET
def etat(request: HttpRequest, commande: str) -> JsonResponse:
    """Le montant, les moyens payables, et le paiement qui occupe déjà la commande s'il y en
    a un (page rechargée, retour de la banque)."""
    cmd = _commande(request, commande)
    try:
        essais = pay().retrouver_paiements(cmd["app_reference"])
        occupant = next((p for p in essais if p.get("status") in OCCUPANTS), None)
        if occupant and occupant["status"] in EN_COURS:
            # Relu seul : la lecture d'un paiement rend aussi ce qui n'est jamais enregistré
            # (le `client_secret` de Stripe).
            occupant = pay().lire_paiement(occupant["id"])
        moyens = [] if occupant else pay().moyens(cmd["currency"], cmd["amount"])
    except ErreurPay as erreur:
        return _erreur(erreur)
    return JsonResponse(
        {
            "amount": cmd["amount"],
            "currency": cmd["currency"],
            "phone": cmd.get("phone") or "",
            "methods": moyens,
            "payment": _public(occupant) if occupant else None,
        }
    )


@require_POST
def payer(request: HttpRequest, commande: str) -> JsonResponse:
    cmd = _commande(request, commande)
    corps = _corps(request)
    if not isinstance(corps.get("method"), str) or not corps["method"]:
        erreur = {"code": "invalid_request", "message": "Choisissez un moyen de paiement."}
        return JsonResponse({"error": erreur}, status=400)
    try:
        paiement = pay().creer_paiement(
            cmd["amount"],
            cmd["currency"],
            corps["method"],
            cmd["app_reference"],
            phone=str(corps.get("phone") or "") or cmd.get("phone") or None,
            email=cmd.get("email"),
            description=cmd.get("description"),
            metadata=cmd.get("metadata"),
        )
    except ErreurPay as erreur:
        return _erreur(erreur)
    return JsonResponse(_public(paiement), status=201)


@require_GET
def suivre(request: HttpRequest, commande: str, paiement: str) -> JsonResponse:
    """Le paiement ; avec `?attendre=1`, la réponse vient dès qu'il est tranché (au plus
    25 s : la page rappelle tant qu'il est en attente)."""
    cmd = _commande(request, commande)
    attendre = ATTENTE_MAX if request.GET.get("attendre") == "1" else 0
    try:
        lu = pay().lire_paiement(paiement, attendre=attendre)
    except ErreurPay as erreur:
        return _erreur(erreur)
    return JsonResponse(_public(_paiement_de(cmd, lu)))


@require_POST
def confirmer(request: HttpRequest, commande: str, paiement: str) -> JsonResponse:
    """Le code OTP saisi par le payeur, ou, sans code, l'approbation PayPal."""
    cmd = _commande(request, commande)
    otp = _corps(request).get("otp")
    try:
        _paiement_de(cmd, pay().lire_paiement(paiement))
        lu = pay().confirmer_paiement(paiement, str(otp) if otp else None)
    except ErreurPay as erreur:
        return _erreur(erreur)
    return JsonResponse(_public(lu))


@require_POST
def annuler(request: HttpRequest, commande: str, paiement: str) -> JsonResponse:
    """Abandonne un paiement en attente, pour changer de moyen."""
    cmd = _commande(request, commande)
    try:
        _paiement_de(cmd, pay().lire_paiement(paiement))
        lu = pay().annuler_paiement(paiement)
    except ErreurPay as erreur:
        return _erreur(erreur)
    return JsonResponse(_public(lu))
