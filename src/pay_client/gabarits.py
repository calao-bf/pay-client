"""Gabarits de messages, écrits dans le code de l'application et poussés à Pay au déploiement
(`python manage.py pay_gabarits`).

Dans n'importe quelle application Django installée, un module `pay_gabarits.py` :

    from pay_client import Gabarit

    GABARITS = [
        Gabarit("code_verification", "Votre code : {code}. Ne le donnez a personne.",
                categorie="code"),
        Gabarit("commande_prete", "Commande {numero} prete.[ Retrait : {lieu}.]",
                facultatives=["lieu"]),
    ]
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Catégories de Pay, avec leurs noms en français.
CATEGORIES = {
    "code": "code",
    "transactionnel": "transactional",
    "transactional": "transactional",
    "information": "information",
}


@dataclass(frozen=True)
class Gabarit:
    """`categorie` : `code` (prioritaire, texte jamais gardé), `transactionnel` (suite d'une
    action de la personne, par défaut) ou `information` (attend la fin des heures calmes, sauf
    `urgent`). `listes` : `{"articles": 5}`, rendue « a, b, c, d, e et 2 autres »."""

    code: str
    texte: str
    categorie: str = "transactionnel"
    facultatives: list[str] = field(default_factory=list)
    listes: dict[str, int] = field(default_factory=dict)
    urgent: bool = False
    garder_texte: bool = True
    garder_numero: bool = True

    def __post_init__(self):
        if self.categorie not in CATEGORIES:
            raise ValueError(
                f"Gabarit {self.code} : catégorie {self.categorie!r} inconnue "
                f"({', '.join(sorted(set(CATEGORIES) - {'transactional'}))})."
            )

    def corps(self) -> dict:
        return {
            "text": self.texte,
            "category": CATEGORIES[self.categorie],
            "optional": list(self.facultatives),
            "lists": dict(self.listes),
            "urgent": self.urgent,
            "keep_body": self.garder_texte,
            "keep_number": self.garder_numero,
        }
