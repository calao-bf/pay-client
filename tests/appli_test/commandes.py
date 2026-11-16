"""La fonction `PAY_COMMANDE` de l'application de test."""

from django.http import Http404

COMMANDES = {"42": 5000, "43": 2000, "44": 1000}


def commande_a_payer(request, commande):
    if commande not in COMMANDES:
        raise Http404
    return {
        "amount": COMMANDES[commande],
        "currency": "XOF",
        "app_reference": f"commande-{commande}",
        "description": f"Commande {commande}",
    }
