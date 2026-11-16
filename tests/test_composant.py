"""Les vues du composant de paiement intégré, contre un faux Pay."""

import json

import pytest
from django.template import Context, Template
from django.test import Client, RequestFactory
from faux_pay import FauxPay

import pay_client
from pay_client import client as module_client

BASE = "/pay/commande/42/"


@pytest.fixture
def faux(monkeypatch):
    monkeypatch.setattr(module_client, "RELANCES", (0.0, 0.0))
    serveur = FauxPay()
    monkeypatch.setattr(pay_client, "_defaut", pay_client.Pay(serveur.url, "ck"))
    yield serveur
    serveur.arreter()


def paiement(**champs):
    base = {
        "id": "pay_1",
        "object": "payment",
        "status": "pending",
        "amount": 5000,
        "currency": "XOF",
        "method": "moov_money",
        "app_reference": "commande-42",
        "next_action": {"type": "ussd_push", "message": "Validez sur votre téléphone."},
        "failure": None,
        "metadata": {"secret_interne": 1},
        "livemode": False,
    }
    return {**base, **champs}


def poster(chemin, corps=None):
    return Client().post(BASE + chemin, json.dumps(corps or {}), content_type="application/json")


def test_etat_sans_paiement_donne_les_moyens(faux):
    faux.reponses += [(200, {"data": []}), (200, {"data": [{"method": "moov_money"}]})]
    reponse = Client().get(BASE)
    assert reponse.status_code == 200
    assert reponse.json() == {
        "amount": 5000,
        "currency": "XOF",
        "phone": "",
        "methods": ["moov_money"],
        "payment": None,
    }
    assert [r["chemin"] for r in faux.recues] == [
        "/v1/payments?app_reference=commande-42",
        "/v1/methods?currency=XOF&amount=5000",
    ]


def test_etat_reprend_le_paiement_en_cours(faux):
    carte = {"type": "card_form", "publishable_key": "pk_x", "client_secret": "pi_secret"}
    faux.reponses += [
        (200, {"data": [paiement(status="failed"), paiement(id="pay_2")][::-1]}),
        (200, paiement(id="pay_2", method="card", next_action=carte)),
    ]
    corps = Client().get(BASE).json()
    assert corps["methods"] == []
    assert corps["payment"]["id"] == "pay_2"
    assert corps["payment"]["next_action"]["client_secret"] == "pi_secret"
    # Ni métadonnées ni référence pour la page.
    assert "metadata" not in corps["payment"] and "app_reference" not in corps["payment"]
    assert faux.recues[1]["chemin"] == "/v1/payments/pay_2"


def test_commande_inconnue_404(faux):
    assert Client().get("/pay/commande/99/").status_code == 404
    assert faux.recues == []


def test_payer_montant_du_serveur(faux):
    faux.reponses.append((201, paiement()))
    reponse = poster("payer/", {"method": "moov_money", "phone": "+22670000000", "amount": 1})
    assert reponse.status_code == 201
    assert reponse.json()["next_action"]["type"] == "ussd_push"
    (requete,) = faux.recues
    assert requete["corps"] == {
        "amount": 5000,
        "currency": "XOF",
        "method": "moov_money",
        "app_reference": "commande-42",
        "customer": {"phone": "+22670000000"},
        "description": "Commande 42",
    }


def test_payer_sans_moyen_400(faux):
    assert poster("payer/", {}).status_code == 400
    assert faux.recues == []


def test_erreur_de_pay_rendue_a_la_page(faux):
    faux.reponses.append(
        (422, {"error": {"code": "method_unavailable", "message": "Moyen indisponible."}})
    )
    reponse = poster("payer/", {"method": "orange_money"})
    assert reponse.status_code == 422
    assert reponse.json() == {
        "error": {"code": "method_unavailable", "message": "Moyen indisponible."}
    }


def test_panne_de_pay_502(faux):
    panne = {"error": {"code": "x", "message": "…", "retryable": True}}
    faux.reponses += [(503, panne)] * 3
    assert poster("payer/", {"method": "moov_money"}).status_code == 502


def test_suivre_attend_le_statut(faux):
    faux.reponses.append((200, paiement(status="succeeded", next_action=None)))
    reponse = Client().get(BASE + "paiements/pay_1/?attendre=1")
    assert reponse.json()["status"] == "succeeded"
    assert faux.recues[0]["chemin"] == "/v1/payments/pay_1?wait=25"


def test_paiement_d_une_autre_commande_404(faux):
    faux.reponses.append((200, paiement(app_reference="commande-43")))
    assert Client().get(BASE + "paiements/pay_1/").status_code == 404
    faux.reponses.append((200, paiement(app_reference="commande-43")))
    assert poster("paiements/pay_1/confirmer/", {"otp": "123456"}).status_code == 404
    # Seulement la lecture : aucune confirmation envoyée à Pay.
    assert all(r["methode"] == "GET" for r in faux.recues)


def test_confirmer_un_code(faux):
    faux.reponses += [(200, paiement()), (200, paiement(status="succeeded"))]
    reponse = poster("paiements/pay_1/confirmer/", {"otp": "123456"})
    assert reponse.json()["status"] == "succeeded"
    assert faux.recues[1]["chemin"] == "/v1/payments/pay_1/confirm"
    assert faux.recues[1]["corps"] == {"otp": "123456"}


def test_annuler(faux):
    faux.reponses += [(200, paiement()), (200, paiement(status="failed"))]
    assert poster("paiements/pay_1/annuler/").json()["status"] == "failed"
    assert faux.recues[1]["chemin"] == "/v1/payments/pay_1/cancel"


def test_balise_du_gabarit():
    requete = RequestFactory().get("/")
    rendu = Template('{% load pay %}{% pay_paiement 42 suite="/merci/" %}').render(
        Context({"request": requete})
    )
    assert 'data-adresse="/pay/commande/42/"' in rendu
    assert 'data-suite="/merci/"' in rendu
    assert "/static/pay_client/paiement.js" in rendu
