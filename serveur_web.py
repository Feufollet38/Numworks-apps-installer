#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Version site local de l’installateur : http://127.0.0.1:8765

Le navigateur sert d’interface, le serveur Python garde la liste d’applis et
parle à la calculatrice par USB via nwlink (le navigateur n’y touche pas).
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import webbrowser
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from catalogue import EMULATEURS
from noyau import IMPORTS, ErreurListe, Liste, fmt_taille

RACINE = Path(__file__).resolve().parent
PAGE = RACINE / "web" / "index.html"
HOTE = "127.0.0.1"
PORT = 8765
SUR_NOM = re.compile(r"[^A-Za-z0-9._-]+")


def nom_sur(nom: str) -> str:
    """Nom de fichier inoffensif : on ne garde que la base, sans chemin."""
    base = Path(nom.replace("\\", "/")).name
    base = SUR_NOM.sub("_", base).lstrip(".")
    return base or "fichier"


class Session:
    """La liste d’applis du site, avec son journal consultable par le navigateur."""

    def __init__(self) -> None:
        self.verrou = threading.Lock()
        self.journal: List[str] = []
        self.liste = Liste(self.log)
        self.occupe = False
        self.tache = ""

    def log(self, msg: str) -> None:
        for ligne in str(msg).rstrip().splitlines() or [""]:
            self.journal.append(ligne)
        del self.journal[:-500]

    def etat(self) -> Dict[str, Any]:
        applis = [
            {
                "index": i,
                "libelle": a.libelle(),
                "nom": a.nom,
                "nwa": a.nwa.name if a.nwa else None,
                "donnees": a.donnees.name if a.donnees else None,
                "besoin_rom": a.besoin_rom(),
                "taille": fmt_taille(a.taille) if a.taille else "—",
            }
            for i, a in enumerate(self.liste.applis)
        ]
        return {
            "catalogue": [{"id": e["id"], "nom": e["nom"]} for e in EMULATEURS],
            "applis": applis,
            "total": fmt_taille(self.liste.total()) if applis else "",
            "occupe": self.occupe,
            "tache": self.tache,
            "journal": self.journal,
        }

    def enregistrer(self, nom: str, contenu: bytes) -> Path:
        IMPORTS.mkdir(parents=True, exist_ok=True)
        dest = IMPORTS / nom_sur(nom)
        dest.write_bytes(contenu)
        return dest

    def lancer(self, essai: bool) -> None:
        """Assemble (et envoie) dans un fil, le navigateur suit par /api/etat."""
        with self.verrou:
            if self.occupe:
                raise ErreurListe("Une opération est déjà en cours.")
            self.liste.verifier()
            self.occupe = True
            self.tache = "essai" if essai else "installation"
            self.journal.clear()

        def travail() -> None:
            try:
                self.liste.installer(essai)
            except ErreurListe as err:
                self.log(str(err))
            except Exception as err:  # le navigateur doit voir la cause
                self.log(f"Erreur inattendue : {err}")
            finally:
                self.occupe = False
                self.tache = ""

        threading.Thread(target=travail, daemon=True).start()


SESSION = Session()


def lire_multipart(corps: bytes, content_type: str) -> Tuple[Dict[str, str], Optional[Tuple[str, bytes]]]:
    """Renvoie (champs texte, (nom de fichier, contenu)) d’un envoi de formulaire."""
    entete = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
    message = BytesParser(policy=HTTP).parsebytes(entete + corps)
    champs: Dict[str, str] = {}
    fichier: Optional[Tuple[str, bytes]] = None
    for part in message.iter_parts():
        nom_fichier = part.get_filename()
        charge = part.get_payload(decode=True) or b""
        if nom_fichier:
            fichier = (nom_fichier, charge)
        else:
            nom = part.get_param("name", header="content-disposition") or ""
            champs[nom] = charge.decode("utf-8", "replace")
    return champs, fichier


class Handler(BaseHTTPRequestHandler):
    server_version = "InstallateurNumWorks/1.0"

    # ------------------------------------------------------------- utilitaires
    def _envoyer(self, code: int, corps: bytes, mime: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, donnees: Dict[str, Any], code: int = 200) -> None:
        self._envoyer(
            code,
            json.dumps(donnees, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _corps(self) -> bytes:
        taille = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(taille) if taille else b""

    def _entier(self, valeur: Any) -> int:
        index = int(valeur)
        if not 0 <= index < len(SESSION.liste.applis):
            raise ErreurListe("Ligne introuvable (la liste a changé ?).")
        return index

    def log_message(self, format: str, *args: Any) -> None:  # silence la console
        pass

    # ----------------------------------------------------------------- routes
    def do_GET(self) -> None:
        chemin = urlparse(self.path).path
        if chemin in ("/", "/index.html"):
            self._envoyer(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif chemin == "/api/etat":
            self._json(SESSION.etat())
        else:
            self._json({"erreur": "Page inconnue."}, 404)

    def do_POST(self) -> None:
        chemin = urlparse(self.path).path
        try:
            self._router(chemin)
        except ErreurListe as err:
            self._json({"erreur": str(err)}, 400)
        except (ValueError, KeyError, TypeError) as err:
            self._json({"erreur": f"Requête invalide : {err}"}, 400)
        except OSError as err:
            self._json({"erreur": f"Erreur fichier : {err}"}, 500)

    def _router(self, chemin: str) -> None:
        type_contenu = self.headers.get("Content-Type", "")
        if chemin in ("/api/nwa", "/api/rom"):
            champs, fichier = lire_multipart(self._corps(), type_contenu)
            if not fichier:
                raise ErreurListe("Aucun fichier reçu.")
            nom, contenu = fichier
            dest = SESSION.enregistrer(nom, contenu)
            if chemin == "/api/nwa":
                SESSION.liste.ajouter_fichier(dest)
            else:
                SESSION.liste.applis[self._entier(champs.get("index"))].donnees = dest
            self._json(SESSION.etat())
            return

        donnees = json.loads(self._corps() or b"{}")
        if chemin == "/api/emulateur":
            SESSION.liste.ajouter_emulateur(str(donnees["id"]))
            threading.Thread(target=SESSION.liste.telecharger, daemon=True).start()
        elif chemin == "/api/retirer":
            SESSION.liste.retirer(self._entier(donnees["index"]))
        elif chemin == "/api/deplacer":
            SESSION.liste.deplacer(self._entier(donnees["index"]), int(donnees["delta"]))
        elif chemin == "/api/vider":
            SESSION.liste.vider()
        elif chemin == "/api/installer":
            SESSION.lancer(essai=bool(donnees.get("essai")))
        else:
            self._json({"erreur": "Action inconnue."}, 404)
            return
        self._json(SESSION.etat())


def main() -> None:
    parseur = argparse.ArgumentParser(description="Installateur NumWorks en site local")
    parseur.add_argument("--port", type=int, default=PORT)
    parseur.add_argument("--hote", default=HOTE, help="127.0.0.1 par défaut (local seulement)")
    parseur.add_argument("--sans-navigateur", action="store_true")
    args = parseur.parse_args()

    serveur = ThreadingHTTPServer((args.hote, args.port), Handler)
    url = f"http://{args.hote}:{serveur.server_address[1]}/"
    print(f"Installateur NumWorks : ouvrez {url}")
    print("Ctrl+C pour arrêter.")
    if not args.sans_navigateur:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        serveur.server_close()


if __name__ == "__main__":
    main()
