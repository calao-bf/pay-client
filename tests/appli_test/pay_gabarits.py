from pay_client import Gabarit

GABARITS = [
    Gabarit("code_verification", "Votre code : {code}.", categorie="code"),
    Gabarit(
        "commande_prete", "Commande {numero} prete.[ Retrait : {lieu}.]", facultatives=["lieu"]
    ),
]
