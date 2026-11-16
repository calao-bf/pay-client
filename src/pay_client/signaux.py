"""Signaux émis à chaque notification vérifiée de Pay (une seule fois par événement).

    from django.dispatch import receiver
    from pay_client.signaux import paiement_reussi

    @receiver(paiement_reussi)
    def activer(sender, evenement, paiement, **kwargs):
        ...  # paiement["app_reference"] : la commande à activer

Les signaux de paiement reçoivent `evenement` (la notification entière) et `paiement` (son
`data`) ; ceux des messages, `evenement` et `message`. Une exception dans un gestionnaire fait
répondre 500 : Pay renverra la notification plus tard.
"""

from django.dispatch import Signal

# Toutes les notifications, quel que soit leur type (`evenement["type"]`).
notification_pay = Signal()

paiement_reussi = Signal()  # payment.succeeded : encaissé, activer le service vendu
paiement_echoue = Signal()  # payment.failed : refusé ou annulé (paiement["failure"]["code"])
paiement_expire = Signal()  # payment.expired : pas de confirmation à temps
paiement_rembourse = Signal()  # payment.refunded : paiement["refund"] décrit le remboursement

message_envoye = Signal()  # message.sent : accepté par l'opérateur
message_recu = Signal()  # message.delivered : reçu par le téléphone
message_echoue = Signal()  # message.failed : échec définitif ou numéro refusé (rejected)
message_bloque = Signal()  # message.blocked : rien n'est parti (failure.code dit pourquoi)

# Type de notification : (signal, nom de l'argument qui reçoit `data`).
PAR_TYPE = {
    "payment.succeeded": (paiement_reussi, "paiement"),
    "payment.failed": (paiement_echoue, "paiement"),
    "payment.expired": (paiement_expire, "paiement"),
    "payment.refunded": (paiement_rembourse, "paiement"),
    "message.sent": (message_envoye, "message"),
    "message.delivered": (message_recu, "message"),
    "message.failed": (message_echoue, "message"),
    "message.blocked": (message_bloque, "message"),
}
