"""De bout en bout contre un vrai Pay (moteur local avec le simulateur, ou le staging avec une
application de test). Lancé seulement si `PAY_INTEGRATION=1`, avec `PAY_URL`, `PAY_API_KEY` et
`PAY_WEBHOOK_SECRET` dans l'environnement. L'application de Pay doit avoir pour URL de webhook
`http://127.0.0.1:8049/notifications` (récepteur lancé ici)."""

import io
import os
import random
import threading
import time
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from django.core.management import call_command
from django.test import override_settings

from pay_client import Pay
from pay_client.signaux import message_envoye, message_recu

pytestmark = pytest.mark.skipif(os.environ.get("PAY_INTEGRATION") != "1", reason="PAY_INTEGRATION")


class Silencieux(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def recepteur():
    from django.core.wsgi import get_wsgi_application

    serveur = make_server("127.0.0.1", 8049, get_wsgi_application(), handler_class=Silencieux)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield
    serveur.shutdown()


@override_settings(
    ROOT_URLCONF="urls_integration",
    PAY_URL=os.environ.get("PAY_URL", ""),
    PAY_API_KEY=os.environ.get("PAY_API_KEY", ""),
    PAY_WEBHOOK_SECRET=os.environ.get("PAY_WEBHOOK_SECRET", ""),
)
def test_gabarits_envoi_et_notifications(recepteur, monkeypatch):
    import pay_client

    monkeypatch.setattr(pay_client, "_defaut", None)
    sortie = io.StringIO()
    call_command("pay_gabarits", stdout=sortie)
    assert "2 gabarit(s) à jour chez Pay." in sortie.getvalue()

    recus = []

    def note(sender, evenement, message, **kwargs):
        recus.append((evenement["type"], message["id"]))

    message_envoye.connect(note)
    message_recu.connect(note)
    try:
        numero = f"+22670{random.randrange(10**6):06d}"
        if numero[-2:] in {"01", "02", "03"}:
            numero = numero[:-2] + "55"
        reference = f"integration-{time.time_ns()}"
        message = pay_client.envoyer_sms(
            numero, "commande_prete", {"numero": "C-42", "lieu": ""}, reference=reference
        )
        assert message["status"] == "queued"
        # Même demande : le même message, aucun second SMS.
        assert (
            pay_client.envoyer_sms(
                numero, "commande_prete", {"numero": "C-42", "lieu": ""}, reference=reference
            )["id"]
            == message["id"]
        )
        fin = time.monotonic() + 30
        while time.monotonic() < fin and len(recus) < 2:
            time.sleep(0.3)
        assert Pay().lire_message(message["id"])["status"] == "delivered"
        assert sorted(recus) == [
            ("message.delivered", message["id"]),
            ("message.sent", message["id"]),
        ]
    finally:
        message_envoye.disconnect(note)
        message_recu.disconnect(note)
