import pytest
from faux_pay import FauxPay

from pay_client import ErreurPay, Pay
from pay_client import client as module_client


@pytest.fixture
def faux(monkeypatch):
    monkeypatch.setattr(module_client, "RELANCES", (0.0, 0.0))
    serveur = FauxPay()
    yield serveur
    serveur.arreter()


def erreur(code, statut=409, **details):
    return (statut, {"error": {"code": code, "message": "…", "details": details or None}})


def test_creation_appel_minimal(faux):
    faux.reponses.append((201, {"id": "pay_1", "status": "pending"}))
    paiement = Pay(faux.url, "ck").creer_paiement(5000, "XOF", "moov_money", "commande-42")
    assert paiement == {"id": "pay_1", "status": "pending"}
    (requete,) = faux.recues
    assert (requete["methode"], requete["chemin"]) == ("POST", "/v1/payments")
    # Rien d'autre que les quatre champs obligatoires : ni country, ni return_url.
    assert requete["corps"] == {
        "amount": 5000,
        "currency": "XOF",
        "method": "moov_money",
        "app_reference": "commande-42",
    }
    assert requete["entetes"]["Idempotency-Key"].startswith("pay:commande-42:")


def test_creation_complete_et_relance_meme_cle(faux):
    indisponible = {"error": {"code": "x", "message": "…", "retryable": True}}
    faux.reponses += [(503, indisponible), (201, {"id": "pay_1", "status": "pending"})]
    Pay(faux.url, "ck").creer_paiement(
        5000,
        "XOF",
        "orange_money",
        "c-1",
        phone="+22670000000",
        description="Abonnement",
        metadata={"plan": "premium"},
    )
    premiere, seconde = faux.recues
    assert premiere["entetes"]["Idempotency-Key"] == seconde["entetes"]["Idempotency-Key"]
    assert seconde["corps"]["customer"] == {"phone": "+22670000000"}
    assert seconde["corps"]["description"] == "Abonnement"
    assert seconde["corps"]["metadata"] == {"plan": "premium"}


def test_creation_doublon_rend_l_existant(faux):
    faux.reponses += [
        erreur("duplicate_app_reference", payment_id="pay_9"),
        (200, {"id": "pay_9", "status": "pending"}),
    ]
    paiement = Pay(faux.url, "ck").creer_paiement(5000, "XOF", "moov_money", "c-1")
    assert paiement["id"] == "pay_9"
    assert faux.recues[1]["chemin"] == "/v1/payments/pay_9"
    # Une autre erreur remonte.
    faux.reponses.append(erreur("method_unavailable", 422))
    with pytest.raises(ErreurPay) as e:
        Pay(faux.url, "ck").creer_paiement(5000, "XOF", "card", "c-2")
    assert e.value.code == "method_unavailable"


def test_montant_entier_obligatoire():
    client = Pay("http://pay.test", "ck")
    for montant in (50.0, "5000", True):
        with pytest.raises(TypeError):
            client.creer_paiement(montant, "XOF", "moov_money", "c")
    with pytest.raises(TypeError):
        client.rembourser("pay_1", 10.5, reference="r")


def test_moyens_et_retrouver(faux):
    faux.reponses += [
        (200, {"object": "list", "data": [{"method": "moov_money"}, {"method": "card"}]}),
        (200, {"object": "list", "data": [{"id": "pay_2"}, {"id": "pay_1"}]}),
    ]
    client = Pay(faux.url, "ck")
    assert client.moyens("XOF", 5000) == ["moov_money", "card"]
    assert faux.recues[0]["chemin"] == "/v1/methods?currency=XOF&amount=5000"
    assert [p["id"] for p in client.retrouver_paiements("c 1")] == ["pay_2", "pay_1"]
    assert faux.recues[1]["chemin"] == "/v1/payments?app_reference=c+1"


def test_attente_du_statut(faux):
    faux.reponses += [
        (200, {"id": "pay_1", "status": "pending"}),
        (200, {"id": "pay_1", "status": "succeeded"}),
    ]
    paiement = Pay(faux.url, "ck").attendre_paiement("pay_1", delai_max=120)
    assert paiement["status"] == "succeeded"
    assert [r["chemin"] for r in faux.recues] == ["/v1/payments/pay_1?wait=25"] * 2


def test_attente_bornee(faux):
    faux.reponses += [(200, {"id": "pay_1", "status": "pending"})] * 2
    paiement = Pay(faux.url, "ck").attendre_paiement("pay_1", delai_max=10)
    assert paiement["status"] == "pending"
    assert [r["chemin"] for r in faux.recues] == ["/v1/payments/pay_1?wait=10"]
    Pay(faux.url, "ck").attendre_paiement("pay_1", delai_max=0)
    assert faux.recues[-1]["chemin"] == "/v1/payments/pay_1"


def test_confirmer_annuler_rembourser(faux):
    client = Pay(faux.url, "ck")
    faux.reponses += [erreur("invalid_otp", 422), (200, {"status": "pending"})]
    with pytest.raises(ErreurPay) as e:
        client.confirmer_paiement("pay_1", "111111")
    assert e.value.code == "invalid_otp"
    client.confirmer_paiement("pay_1", "123456")
    faux_code, bon_code = faux.recues
    assert faux_code["chemin"] == "/v1/payments/pay_1/confirm"
    assert (faux_code["corps"], bon_code["corps"]) == ({"otp": "111111"}, {"otp": "123456"})
    # Un nouveau code : une nouvelle clé (sinon Pay répondrait idempotency_key_reused).
    assert faux_code["entetes"]["Idempotency-Key"] != bon_code["entetes"]["Idempotency-Key"]

    client.confirmer_paiement("pay_2")  # PayPal approuvé : aucun code
    assert faux.recues[-1]["corps"] == {}

    client.annuler_paiement("pay_3")
    assert faux.recues[-1]["chemin"] == "/v1/payments/pay_3/cancel"
    assert faux.recues[-1]["entetes"]["Idempotency-Key"] == "cancel:pay_3"

    client.rembourser("pay_4", reference="avoir-1")
    client.rembourser("pay_4", 2000, reference="avoir-2", reason="article manquant")
    tout, partie = faux.recues[-2:]
    assert (tout["chemin"], tout["corps"]) == ("/v1/payments/pay_4/refunds", {})
    assert partie["corps"] == {"amount": 2000, "reason": "article manquant"}
    assert partie["entetes"]["Idempotency-Key"] == "refund:pay_4:avoir-2"
