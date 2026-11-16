# pay-client

Client Python de **Pay**, l'orchestrateur de paiements et de messages du parc Calao, côté
serveur de l'application : **paiements** (depuis 0.2) et **messages (SMS)**.

Aucune dépendance. Le volet Django (vue des notifications, signaux, commande des gabarits) est
facultatif.

## Installation

```bash
pip install "pay-client @ git+https://github.com/calao-bf/pay-client@v0.2.0"
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

Si l'application envoie des SMS, à chaque déploiement, après les migrations :

```bash
python manage.py pay_gabarits
```

## Paiements

Le payeur ne quitte jamais l'écran de l'application : ni redirection, ni page hébergée. Le
serveur crée le paiement, la page montre `next_action`, et le statut arrive à la seconde.

```python
from pay_client import pay

pay().moyens("XOF", 5000)          # ["moov_money", "orange_money", …] : un bouton par moyen

paiement = pay().creer_paiement(
    5000, "XOF", "moov_money", f"commande-{commande.pk}",
    phone="+22670000000",           # obligatoire pour Orange et Moov
)
# paiement["id"] : "pay_…" ; paiement["next_action"] : ce que la page montre au payeur

paiement = pay().attendre_paiement(paiement["id"])   # au plus 2 minutes, par défaut
# "succeeded", "failed" (paiement["failure"]["code"]), "expired",
# ou encore "pending" : afficher « paiement en cours de vérification, vous serez prévenu »
```

- Montant : un **entier**, dans la plus petite unité de la devise (5000 XOF ; 2000 = 20,00 USD).
  Un float lève `TypeError`.
- Seuls `amount`, `currency`, `method` et la référence de la commande sont obligatoires ;
  `phone`, `email`, `description` et `metadata` (renvoyées dans les notifications) sont
  facultatifs. Le pays du payeur est déduit de son téléphone.
- Une commande n'a qu'un paiement en cours ou encaissé : rappeler `creer_paiement` pour la même
  commande (double clic, page rechargée) **renvoie ce paiement-là**, sans en créer un second.
  Après un `failed` ou un `expired`, un nouvel appel crée un nouvel essai.

`next_action["type"]` dit quoi montrer :

| `type` | La page |
|---|---|
| `ussd_push` / `ussd_or_otp` | affiche `message` : le payeur valide sur son téléphone |
| `otp_input` | affiche `message` et `ussd_code`, demande le code, puis le serveur appelle `confirmer_paiement(id, code)` |
| `card_form` | Payment Element de Stripe avec `publishable_key` et `client_secret` |
| `paypal_buttons` | boutons PayPal avec `client_id` et `order_id`, puis `confirmer_paiement(id)` après l'approbation |

Les autres gestes :

```python
pay().confirmer_paiement(paiement_id, "123456")   # code OTP (Orange) ; sans code : PayPal
pay().annuler_paiement(paiement_id)               # encore en attente seulement
pay().rembourser(paiement_id, reference="avoir-17")                    # tout
pay().rembourser(paiement_id, 2000, reference="avoir-18", reason="…")  # une partie
pay().retrouver_paiements(f"commande-{commande.pk}")   # tous les essais, le plus récent d'abord
pay().lire_paiement(paiement_id)
```

- Code OTP refusé : `ErreurPay` 422 (`invalid_otp`, `otp_expired`, `otp_amount_mismatch`) ;
  le paiement attend un nouveau code : garder l'étape « code », afficher `erreur.message`.
- `rembourser` : `reference` identifie le remboursement dans l'application ; rappeler avec la
  même référence ne rembourse pas deux fois.

**C'est la notification qui active le service vendu**, jamais l'attente ni la page :

```python
from django.dispatch import receiver
from pay_client.signaux import paiement_reussi

@receiver(paiement_reussi)
def activer(sender, evenement, paiement, **kwargs):
    commande = Commande.objects.get(pk=paiement["app_reference"].removeprefix("commande-"))
    commande.activer()   # une seule fois par événement ; à écrire sans risque s'il est rejoué
```

Signaux : `paiement_reussi`, `paiement_echoue`, `paiement_expire`, `paiement_rembourse`
(`paiement["refund"]` décrit le remboursement). Chacun reçoit `evenement` et `paiement`.

En staging, le simulateur de Pay choisit l'issue par `metadata={"simulation": "echec"}`
(`succes` par défaut, `otp` avec le code `123456`, `delai`, `indisponible`…).

## Messages

### Gabarits

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

### Envoyer un SMS

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
