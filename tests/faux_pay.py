"""Un faux Pay en HTTP local : enregistre les requêtes, répond selon un script."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FauxPay:
    def __init__(self):
        self.recues: list[dict] = []
        self.reponses: list[tuple[int, dict]] = []  # dépilées dans l'ordre ; sinon 200 {}
        faux = self

        class Gestion(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _repondre(self):
                longueur = int(self.headers.get("Content-Length") or 0)
                corps = self.rfile.read(longueur) if longueur else b""
                faux.recues.append(
                    {
                        "methode": self.command,
                        "chemin": self.path,
                        "entetes": dict(self.headers),
                        "corps": json.loads(corps) if corps else None,
                    }
                )
                statut, reponse = faux.reponses.pop(0) if faux.reponses else (200, {})
                donnees = json.dumps(reponse).encode()
                self.send_response(statut)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            do_GET = do_POST = do_PUT = _repondre

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def arreter(self):
        self.serveur.shutdown()
