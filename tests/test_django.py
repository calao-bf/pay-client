import io
import json

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import Client
from faux_pay import FauxPay

import pay_client
from pay_client import signer
from pay_client.signaux import (
    message_echoue,
    message_recu,
    notification_pay,
    paiement_echoue,
    paiement_expire,
    paiement_rembourse,
    paiement_reussi,
)

SECRET = "whsec_essai"


def notification(type_="message.delivered", identifiant="evt_1"):
    return json.dumps(
        {
            "id": identifiant,
            "type": type_,
            "created_at": "2026-11-13T19:00:00Z",
            "data": {"id": "msg_1", "object": "message", "status": "delivered"},
        }
    ).encode()


def poster(corps, entete):
    return Client().post(
        "/pay/webhook/", corps, content_type="application/json", headers={"X-Signature": entete}
    )


@pytest.fixture(autouse=True)
def vider_cache():
    cache.clear()


def test_notification_verifiee_une_seule_fois():
    recus = []

    def gestionnaire(sender, evenement, message, **kwargs):
        recus.append((evenement["type"], message["id"]))

    message_recu.connect(gestionnaire)
    try:
        corps = notification()
        assert poster(corps, signer(SECRET, corps)).status_code == 200
        # Le même événement une seconde fois : 200, rien de plus.
        assert poster(corps, signer(SECRET, corps)).status_code == 200
    finally:
        message_recu.disconnect(gestionnaire)
    assert recus == [("message.delivered", "msg_1")]


def test_signaux_de_paiement():
    recus = []

    def note(sender, evenement, paiement, **kwargs):
        recus.append((evenement["type"], paiement["app_reference"]))

    signaux = (paiement_reussi, paiement_echoue, paiement_expire, paiement_rembourse)
    for signal in signaux:
        signal.connect(note)
    try:
        for n, type_ in enumerate(
            ["payment.succeeded", "payment.failed", "payment.expired", "payment.refunded"]
        ):
            corps = json.dumps(
                {
                    "id": f"evt_p{n}",
                    "type": type_,
                    "data": {"id": "pay_1", "object": "payment", "app_reference": "c-42"},
                }
            ).encode()
            assert poster(corps, signer(SECRET, corps)).status_code == 200
    finally:
        for signal in signaux:
            signal.disconnect(note)
    assert recus == [
        ("payment.succeeded", "c-42"),
        ("payment.failed", "c-42"),
        ("payment.expired", "c-42"),
        ("payment.refunded", "c-42"),
    ]


def test_signature_refusee_et_rotation():
    corps = notification(identifiant="evt_2")
    assert poster(corps, signer("whsec_autre", corps)).status_code == 400
    assert poster(corps, "").status_code == 400
    assert poster(corps, "t=1,v1").status_code == 400
    assert poster(corps, signer(SECRET, corps, t=1)).status_code == 400  # trop ancienne
    # Rotation : deux v1, l'ancienne d'abord.
    ancien = signer("whsec_ancien", corps)
    t = ancien.split(",")[0]
    nouveau = signer(SECRET, corps, t=int(t[2:])).split(",")[1]
    assert poster(corps, f"{ancien},{nouveau}").status_code == 200
    assert Client().get("/pay/webhook/").status_code == 405


def test_erreur_du_gestionnaire_pay_renverra():
    def casse(sender, **kwargs):
        raise RuntimeError("base indisponible")

    message_echoue.connect(casse)
    corps = notification("message.failed", "evt_3")
    try:
        with pytest.raises(RuntimeError):
            poster(corps, signer(SECRET, corps))
    finally:
        message_echoue.disconnect(casse)
    # Pas mémorisé : la nouvelle tentative de Pay sera traitée.
    vus = []
    notification_pay.connect(
        lambda sender, evenement, **kw: vus.append(evenement["id"]), weak=False, dispatch_uid="t"
    )
    try:
        assert poster(corps, signer(SECRET, corps)).status_code == 200
    finally:
        notification_pay.disconnect(dispatch_uid="t")
    assert vus == ["evt_3"]


def test_commande_pay_gabarits(monkeypatch):
    faux = FauxPay()
    monkeypatch.setattr(pay_client, "_defaut", pay_client.Pay(faux.url, "ck"))
    faux.reponses += [(201, {"version": 1}), (200, {"version": 3})]
    sortie = io.StringIO()
    try:
        call_command("pay_gabarits", stdout=sortie)
        assert sorted(r["chemin"] for r in faux.recues) == [
            "/v1/templates/code_verification",
            "/v1/templates/commande_prete",
        ]
        assert "2 gabarit(s) à jour chez Pay." in sortie.getvalue()
        faux.reponses.append(
            (
                400,
                {
                    "error": {
                        "code": "invalid_request",
                        "message": "Texte.",
                        "details": {"text": ["…"]},
                    }
                },
            )
        )
        with pytest.raises(CommandError):
            call_command("pay_gabarits", stdout=io.StringIO())
    finally:
        faux.arreter()
