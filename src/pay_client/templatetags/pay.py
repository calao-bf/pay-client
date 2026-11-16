"""`{% load pay %}{% pay_paiement commande %}` : le composant de paiement dans la page.

`commande` : l'identifiant que la fonction `PAY_COMMANDE` reçoit. `suite` (facultatif) :
l'adresse où envoyer le payeur une fois le paiement reçu.
"""

from __future__ import annotations

from django import template
from django.middleware.csrf import get_token
from django.urls import reverse

register = template.Library()


@register.inclusion_tag("pay_client/paiement.html", takes_context=True)
def pay_paiement(context, commande, suite=""):
    # Sans le processeur de contexte `request`, le jeton CSRF que Django fournit toujours.
    requete = context.get("request")
    return {
        "adresse": reverse("pay_client:etat", args=[str(commande)]),
        "csrf": get_token(requete) if requete else context.get("csrf_token", ""),
        "suite": suite,
    }
