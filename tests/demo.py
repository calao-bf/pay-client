"""Démonstration locale du composant, sans Pay : un faux Pay en mémoire et une page de commande.

    uv run --extra dev python tests/demo.py 8765      # puis http://127.0.0.1:8765/payer/42/

Moov : réussit 6 s après la création. Orange : code 123456. Carte et PayPal : leur formulaire
ne peut pas s'afficher sans vraies clés (essai réel : contre le staging).
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..", "src"), os.path.dirname(__file__)]

PAIEMENTS: dict[str, dict] = {}
NUMEROS = itertools.count(1)
VERROU = threading.Lock()


def avancer(p: dict) -> None:
    if p["status"] == "pending" and p["method"] == "moov_money" and time.time() - p["_t"] > 6:
        p["status"], p["next_action"] = "succeeded", None


class FauxPay(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def repondre(self, statut: int, corps) -> None:
        donnees = json.dumps(corps).encode()
        self.send_response(statut)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)

    def public(self, p: dict) -> dict:
        return {k: v for k, v in p.items() if not k.startswith("_")}

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/v1/methods":
            moyens = ["moov_money", "orange_money", "card", "paypal"]
            return self.repondre(200, {"data": [{"method": m} for m in moyens]})
        if url.path == "/v1/payments":
            ref = q["app_reference"][0]
            with VERROU:
                trouves = [p for p in PAIEMENTS.values() if p["app_reference"] == ref]
            return self.repondre(200, {"data": [self.public(p) for p in reversed(trouves)]})
        p = PAIEMENTS.get(url.path.rsplit("/", 1)[-1])
        if not p:
            return self.repondre(404, {"error": {"code": "not_found", "message": "Inconnu."}})
        fin = time.time() + int(q.get("wait", ["0"])[0])
        while True:
            avancer(p)
            if p["status"] != "pending" or time.time() >= fin:
                return self.repondre(200, self.public(p))
            time.sleep(0.5)

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        morceaux = self.path.split("/")
        if self.path == "/v1/payments":
            with VERROU:
                for p in PAIEMENTS.values():
                    if p["app_reference"] == corps["app_reference"] and p["status"] in (
                        "pending",
                        "succeeded",
                    ):
                        erreur = {"code": "duplicate_app_reference", "message": "Déjà en cours."}
                        erreur["details"] = {"payment_id": p["id"]}
                        return self.repondre(409, {"error": erreur})
                ident = f"pay_demo{next(NUMEROS)}"
                actions = {
                    "moov_money": {"type": "ussd_push", "message": "Validez sur votre Moov."},
                    "orange_money": {
                        "type": "otp_input",
                        "message": "Composez le code USSD, puis saisissez le code reçu (123456).",
                        "ussd_code": f"*144*4*6*{corps['amount']}#",
                    },
                    "card": {"type": "card_form", "publishable_key": "pk_test_demo"},
                    "paypal": {"type": "paypal_buttons", "client_id": "demo", "order_id": "O1"},
                }
                p = PAIEMENTS[ident] = {
                    "id": ident,
                    "status": "pending",
                    "amount": corps["amount"],
                    "currency": corps["currency"],
                    "method": corps["method"],
                    "app_reference": corps["app_reference"],
                    "next_action": actions[corps["method"]],
                    "failure": None,
                    "livemode": False,
                    "_t": time.time(),
                }
            return self.repondre(201, self.public(p))
        p = PAIEMENTS.get(morceaux[3])
        if morceaux[-1] == "confirm":
            if corps.get("otp") != "123456":
                erreur = {"code": "invalid_otp", "message": "Code incorrect."}
                return self.repondre(422, {"error": erreur})
            p["status"], p["next_action"] = "succeeded", None
        elif morceaux[-1] == "cancel":
            p["status"] = "failed"
            p["failure"] = {"code": "cancelled", "message": "Annulé."}
        return self.repondre(200, self.public(p))


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    faux = ThreadingHTTPServer(("127.0.0.1", 0), FauxPay)
    threading.Thread(target=faux.serve_forever, daemon=True).start()

    from django.conf import settings

    settings.configure(
        DEBUG=True,
        SECRET_KEY="demo",
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["*"],
        INSTALLED_APPS=["django.contrib.staticfiles", "pay_client", "appli_test"],
        MIDDLEWARE=["django.middleware.csrf.CsrfViewMiddleware"],
        TEMPLATES=[
            {"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}
        ],
        STATIC_URL="/static/",
        PAY_URL=f"http://127.0.0.1:{faux.server_address[1]}",
        PAY_API_KEY="ck_demo",
        PAY_COMMANDE="appli_test.commandes.commande_a_payer",
    )
    import django

    django.setup()
    from django.core.management import call_command

    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False)


PAGE = """{% load pay %}<!doctype html><meta charset="utf-8">
<title>Commande {{ commande }}</title><h1>Commande {{ commande }}</h1>
{% pay_paiement commande %}"""


def page(request, commande):
    from django.http import HttpResponse
    from django.template import engines

    gabarit = engines["django"].from_string(PAGE)
    return HttpResponse(gabarit.render({"commande": commande}, request))


def _urls():
    from django.urls import include, path

    return [path("pay/", include("pay_client.urls")), path("payer/<str:commande>/", page)]


def __getattr__(nom):
    if nom == "urlpatterns":
        return _urls()
    raise AttributeError(nom)


if __name__ == "__main__":
    main()
