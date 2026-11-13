"""Pousse à Pay tous les gabarits déclarés dans les modules `pay_gabarits.py` des applications
installées. À lancer à chaque déploiement, après les migrations : un gabarit inchangé ne change
rien chez Pay."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import autodiscover_modules

from pay_client import ErreurPay, Gabarit, pay


def gabarits_declares() -> list[Gabarit]:
    import sys

    modules = [
        m
        for nom, m in list(sys.modules.items())
        if nom == "pay_gabarits" or nom.endswith(".pay_gabarits")
    ]
    tous: dict[str, Gabarit] = {}
    for module in modules:
        for gabarit in getattr(module, "GABARITS", []):
            if gabarit.code in tous and tous[gabarit.code] != gabarit:
                raise CommandError(f"Gabarit {gabarit.code} déclaré deux fois, différemment.")
            tous[gabarit.code] = gabarit
    return list(tous.values())


class Command(BaseCommand):
    help = "Déclare chez Pay les gabarits de messages de l'application (pay_gabarits.py)."

    def handle(self, *args, **options):
        autodiscover_modules("pay_gabarits")
        gabarits = gabarits_declares()
        if not gabarits:
            self.stdout.write("Aucun gabarit déclaré (module pay_gabarits.py, liste GABARITS).")
            return
        for gabarit in gabarits:
            try:
                lu = pay().pousser_gabarit(gabarit)
            except ErreurPay as erreur:
                raise CommandError(
                    f"Gabarit {gabarit.code} refusé par Pay : {erreur.code}, {erreur.message} "
                    f"{erreur.details or ''}"
                ) from erreur
            self.stdout.write(f"{gabarit.code} : version {lu['version']}")
        self.stdout.write(self.style.SUCCESS(f"{len(gabarits)} gabarit(s) à jour chez Pay."))
