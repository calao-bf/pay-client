"""La vue qui reçoit les notifications de Pay. Dans `urls.py` du projet :

    path("pay/", include("pay_client.urls")),   # → /pay/webhook/

puis, dans la Gestion de Pay, l'URL de webhook de l'application : https://<site>/pay/webhook/.
"""

from __future__ import annotations

import json
import logging

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .client import _reglage
from .signature import signature_valide
from .signaux import PAR_TYPE, notification_pay

journal = logging.getLogger("pay_client")

# Un même événement peut arriver deux fois : il est mémorisé 8 jours (Pay relance pendant
# environ 33 h au plus).
DUREE_MEMOIRE_S = 8 * 24 * 3600


@csrf_exempt
@require_POST
def webhook(request: HttpRequest) -> HttpResponse:
    corps = request.body
    if not signature_valide(
        _reglage("PAY_WEBHOOK_SECRET"), corps, request.headers.get("X-Signature", "")
    ):
        journal.warning("Notification de Pay refusée : signature invalide.")
        return HttpResponse(status=400)
    try:
        evenement = json.loads(corps)
        identifiant, type_ = evenement["id"], evenement["type"]
    except (ValueError, KeyError, TypeError):
        return HttpResponse(status=400)
    cle = f"pay_client:evenement:{identifiant}"
    if cache.get(cle):
        return HttpResponse(status=200)
    donnees = evenement.get("data") or {}
    notification_pay.send(sender=webhook, evenement=evenement)
    if type_ in PAR_TYPE:
        signal, nom = PAR_TYPE[type_]
        signal.send(sender=webhook, evenement=evenement, **{nom: donnees})
    cache.set(cle, 1, DUREE_MEMOIRE_S)
    return HttpResponse(status=200)
