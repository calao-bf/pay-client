import pytest
from faux_pay import FauxPay

import pay_client
from pay_client import ErreurPay, Gabarit, Pay
from pay_client import client as module_client


@pytest.fixture
def faux(monkeypatch):
    monkeypatch.setattr(module_client, "RELANCES", (0.0, 0.0))
    serveur = FauxPay()
    yield serveur
    serveur.arreter()


def test_envoi_d_un_sms(faux):
    faux.reponses.append((202, {"id": "msg_1", "status": "queued"}))
    message = Pay(faux.url, "ck_test_x").envoyer_message(
        "70 12 34 56", "commande_prete", {"numero": "C-42"}, reference="commande:42"
    )
    assert message == {"id": "msg_1", "status": "queued"}
    (requete,) = faux.recues
    assert (requete["methode"], requete["chemin"]) == ("POST", "/v1/messages")
    assert requete["entetes"]["Authorization"] == "Bearer ck_test_x"
    # Clé d'idempotence fabriquée à partir de la référence : un nouvel essai ne double rien.
    assert requete["entetes"]["Idempotency-Key"] == "msg:commande:42"
    assert requete["entetes"]["User-Agent"].startswith("pay-client-python/")
    assert requete["corps"] == {
        "to": "70 12 34 56",
        "template": "commande_prete",
        "context": {"numero": "C-42"},
        "reference": "commande:42",
    }


def test_relance_si_pay_indisponible_puis_erreur(faux):
    indisponible = {"error": {"code": "provider_unavailable", "message": "…", "retryable": True}}
    faux.reponses += [(503, indisponible), (202, {"id": "msg_1"})]
    client = Pay(faux.url, "ck")
    assert client.envoyer_message("70123456", "t", reference="r")["id"] == "msg_1"
    assert [r["entetes"]["Idempotency-Key"] for r in faux.recues] == ["msg:r", "msg:r"]

    faux.reponses.append(
        (
            422,
            {
                "error": {
                    "code": "template_variable_missing",
                    "message": "Variable absente.",
                    "details": {"missing": ["numero"]},
                    "retryable": False,
                }
            },
        )
    )
    with pytest.raises(ErreurPay) as erreur:
        client.envoyer_message("70123456", "commande_prete", reference="r2")
    assert (erreur.value.status, erreur.value.code) == (422, "template_variable_missing")
    assert erreur.value.details == {"missing": ["numero"]}
    assert len(faux.recues) == 3  # pas de relance d'une erreur définitive


def test_panne_reseau(monkeypatch):
    monkeypatch.setattr(module_client, "RELANCES", (0.0, 0.0))
    with pytest.raises(ErreurPay) as erreur:
        Pay("http://127.0.0.1:9", "ck", delai=2)._appel("GET", "/v1/templates")
    assert (erreur.value.status, erreur.value.code) == (0, "network_error")


def test_gabarit_pousse_et_apercu(faux):
    faux.reponses += [(201, {"code": "c", "version": 1}), (200, {"text": "Code 1234."})]
    client = Pay(faux.url, "ck")
    assert client.pousser_gabarit(Gabarit("c", "Code {code}.", categorie="code"))["version"] == 1
    assert faux.recues[0]["methode"] == "PUT"
    assert faux.recues[0]["corps"]["category"] == "code"
    assert "Idempotency-Key" not in faux.recues[0]["entetes"]
    assert client.apercu("c", {"code": "1234"}) == {"text": "Code 1234."}
    assert faux.recues[1]["entetes"]["Idempotency-Key"].startswith("apercu:")


def test_categories():
    assert Gabarit("a", "x", categorie="transactionnel").corps()["category"] == "transactional"
    assert Gabarit("a", "x").corps()["keep_body"] is True
    with pytest.raises(ValueError):
        Gabarit("a", "x", categorie="promo")


def test_reglages_obligatoires(monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "PAY_URL", "")
    monkeypatch.delenv("PAY_URL", raising=False)
    with pytest.raises(ValueError):
        Pay()
    monkeypatch.setattr(settings, "PAY_URL", "http://pay.test/")
    assert Pay().url == "http://pay.test"
    assert pay_client.__version__ == "0.3.0"
