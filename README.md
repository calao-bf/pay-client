# pay-client

Client Python de **Pay**, l'orchestrateur de paiements et de messages du parc Calao. Version
0.1 : les **messages (SMS)**. Les paiements arrivent dans une version suivante.

Aucune dépendance. Le volet Django (vue des notifications, signaux, commande des gabarits) est
facultatif.

## Installation

```bash
pip install "pay-client @ git+https://github.com/calao-bf/pay-client@v0.1.0"
```

## Réglages

Trois variables, en réglages Django ou en variables d'environnement :

| Nom | Valeur |
|---|---|
| `PAY_URL` | l'adresse de Pay (staging ou production) |
| `PAY_API_KEY` | la clé d'API de l'application (`ck_…`), donnée par l’équipe de Pay |
| `PAY_WEBHOOK_SECRET` | le secret de signature des notifications (`whsec_…`), donné par l’équipe de Pay |

La clé reste sur le serveur de l'application : jamais dans un navigateur ni une appli mobile.

## Django : trois lignes

```python
# settings.py
INSTALLED_APPS += ["pay_client"]

# urls.py
path("pay/", include("pay_client.urls")),   # notifications : https://<site>/pay/webhook/
```

À chaque déploiement, après les migrations :

```bash
python manage.py pay_gabarits
```

## Gabarits

Aucun texte libre n'est envoyé : chaque SMS part d'un gabarit écrit dans le code de
l'application. Dans n'importe quelle application Django du projet, un module `pay_gabarits.py` :

```python
from pay_client import Gabarit

GABARITS = [
    Gabarit("code_verification", "Votre code : {code}. Ne le donnez a personne.",
            categorie="code"),
    Gabarit("commande_prete", "Commande {numero} prete.[ Retrait : {lieu}.]",
            facultatives=["lieu"]),
]
```

- `categorie` : `code` (prioritaire, texte jamais gardé), `transactionnel` (par défaut : suite
  d'une action de la personne) ou `information` (attend la fin des heures calmes, sauf
  `urgent=True`).
- `[ … ]` : morceau rendu seulement si toutes ses variables sont remplies.
- `listes={"articles": 5}` : la variable reçoit une liste, rendue « a, b, c, d, e et 2 autres ».
- `garder_texte`, `garder_numero` : garder le texte et le numéro en clair chez Pay après l'envoi.

`python manage.py pay_gabarits` les déclare tous chez Pay. Un gabarit inchangé ne change rien :
la commande peut tourner à chaque déploiement.

## Envoyer un SMS

```python
from pay_client import envoyer_sms

message = envoyer_sms(
    "70 12 34 56",
    "commande_prete",
    {"numero": "C-42", "lieu": "Ouaga 2000"},
    reference=f"commande-prete:{commande.pk}",
)
# message["id"] : "msg_…", message["status"] : "queued"
```

- `reference` : unique par message (100 caractères au plus). Renvoyer la même demande renvoie
  le même message, sans second SMS : un nouvel essai après une coupure est sans risque.
- Le numéro : `70123456`, `70 12 34 56`, `0022670123456` ou `+22670123456`.
- Pay momentanément indisponible : le paquet réessaie deux fois, puis lève `ErreurPay`.

Une erreur lève `ErreurPay` (`status`, `code`, `message`, `details`) : par exemple
`template_variable_missing` avec `details["missing"]`, ou `text_too_long`.

## Suivre les messages

Pay notifie chaque changement d'état. La vue du paquet vérifie la signature, ne traite chaque
événement qu'une fois et émet un signal :

```python
from django.dispatch import receiver
from pay_client.signaux import message_bloque, message_echoue

@receiver(message_echoue)
def sms_echoue(sender, evenement, message, **kwargs):
    # message["status"] : failed ou rejected ; message["failure"]["code"]
    ...

@receiver(message_bloque)
def sms_bloque(sender, evenement, message, **kwargs):
    # Rien n'est parti : limit_reached, real_sending_disabled, number_not_allowed…
    ...
```

Signaux : `message_envoye`, `message_recu`, `message_echoue`, `message_bloque`, et
`notification_pay` pour toutes les notifications. Une exception dans un gestionnaire fait
répondre 500 : Pay renverra la notification plus tard.

La mémoire des événements déjà traités passe par le cache Django : en production, un cache
partagé (Redis), pas le cache en mémoire par processus.

## En test

Une application de test sans compte de messagerie passe par le simulateur de Pay : aucun vrai
SMS. Scénarios par la fin du numéro : `…01` refusé, `…02` panne, `…03` jamais reçu.

Pour tester sa propre vue de notifications :

```python
from pay_client import signer
corps = b'{"id": "evt_1", "type": "message.delivered", "data": {...}}'
client.post("/pay/webhook/", corps, content_type="application/json",
            headers={"X-Signature": signer(settings.PAY_WEBHOOK_SECRET, corps)})
```

## Développement

```bash
pip install -e ".[dev]"
pytest
```

`PAY_INTEGRATION=1` (avec `PAY_URL`, `PAY_API_KEY`, `PAY_WEBHOOK_SECRET`) lance aussi l'essai de
bout en bout contre un vrai Pay.
