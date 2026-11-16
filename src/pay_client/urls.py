from django.urls import path

from . import composant
from .vues import webhook

app_name = "pay_client"
urlpatterns = [
    path("webhook/", webhook, name="webhook"),
    # Le composant de paiement intégré (`{% pay_paiement commande %}`).
    path("commande/<str:commande>/", composant.etat, name="etat"),
    path("commande/<str:commande>/payer/", composant.payer, name="payer"),
    path("commande/<str:commande>/paiements/<str:paiement>/", composant.suivre, name="suivre"),
    path(
        "commande/<str:commande>/paiements/<str:paiement>/confirmer/",
        composant.confirmer,
        name="confirmer",
    ),
    path(
        "commande/<str:commande>/paiements/<str:paiement>/annuler/",
        composant.annuler,
        name="annuler",
    ),
]
