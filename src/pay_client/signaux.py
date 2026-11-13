"""Signaux émis à chaque notification vérifiée de Pay (une seule fois par événement).

    from django.dispatch import receiver
    from pay_client.signaux import message_echoue

    @receiver(message_echoue)
    def sms_rate(sender, evenement, message, **kwargs):
        ...  # message["status"] : failed ou rejected ; message["failure"]["code"]

Chaque gestionnaire reçoit `evenement` (la notification entière) et `message` (son `data`).
Une exception dans un gestionnaire fait répondre 500 : Pay renverra la notification plus tard.
"""

from django.dispatch import Signal

# Toutes les notifications, quel que soit leur type (`evenement["type"]`).
notification_pay = Signal()

message_envoye = Signal()  # message.sent : accepté par l'opérateur
message_recu = Signal()  # message.delivered : reçu par le téléphone
message_echoue = Signal()  # message.failed : échec définitif ou numéro refusé (rejected)
message_bloque = Signal()  # message.blocked : rien n'est parti (failure.code dit pourquoi)

PAR_TYPE = {
    "message.sent": message_envoye,
    "message.delivered": message_recu,
    "message.failed": message_echoue,
    "message.blocked": message_bloque,
}
