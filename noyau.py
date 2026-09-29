"""Cœur commun aux deux interfaces (fenêtre tkinter et site local).

Gère la liste d'applis à installer, le téléchargement des .nwa du catalogue et
l'appel à nwlink pour tout envoyer en un seul flash.
"""

from __future__ import annotations

import subprocess
import json
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import PurePosixPath
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from catalogue import EMULATEURS
from nwlink_multi import (
    ErreurNwlink,
    commande_essai,
    commande_multi,
    commande_simple,
    trouver_npm,
    trouver_npx,
)

RACINE = Path(__file__).resolve().parent
CACHE = RACINE / "telechargements"
IMPORTS = CACHE / "importees"
PRESETS = CACHE / "presets"
RUNTIME = CACHE / "nwlink-runtime"
MANIFESTE = CACHE / "install-multi.json"
IMAGE_ESSAI = CACHE / "essai-applis.bin"
LIMITE_SITE_MO = 2.5
LIMITE_FLASH_MO = 8.0
BESOIN_ROM = ("peanutgb", "peanutgbc", "nofrendo")

Journal = Callable[[str], None]


def fmt_taille(n: int) -> str:
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} Ko"
    return f"{n / (1024 * 1024):.2f} Mo"


def emul_par_id(identifiant: str) -> Optional[dict]:
    for e in EMULATEURS:
        if e["id"] == identifiant:
            return e
    return None


class Appli:
    """Une appli de la liste : un .nwa et, éventuellement, ses données externes."""

    def __init__(self, nom: str, nwa: Optional[Path] = None, emul: Optional[dict] = None):
        self.nom = nom
        self.nwa = nwa
        self.emul = emul
        self.donnees: Optional[Path] = None

    @property
    def taille(self) -> int:
        total = 0
        for chemin in (self.nwa, self.donnees):
            if chemin and chemin.is_file():
                total += chemin.stat().st_size
        return total

    def libelle(self) -> str:
        """Nom affiché : la ROM distingue deux copies du même émulateur."""
        if self.donnees:
            return f"{self.nom} — {self.donnees.stem}"
        return self.nom

    def besoin_rom(self) -> bool:
        return bool(self.emul) and self.emul["id"] in BESOIN_ROM


class ErreurListe(RuntimeError):
    """La liste d'applis n'est pas installable telle quelle."""


class Liste:
    """La liste d'applis, et tout ce qu'on peut en faire."""

    def __init__(self, log: Journal):
        self.applis: List[Appli] = []
        self.log = log
        self._verrou_dl = threading.Lock()

    # ------------------------------------------------------------------ édition
    def ajouter_emulateur(self, identifiant: str) -> Appli:
        emul = emul_par_id(identifiant)
        if not emul:
            raise ErreurListe(f"Émulateur inconnu : {identifiant}")
        appli = Appli(emul["nom"], emul=emul)
        cache = CACHE / emul["fichier"]
        if cache.is_file():
            appli.nwa = cache
        self.applis.append(appli)
        return appli

    def ajouter_fichier(self, chemin: Path) -> Appli:
        appli = Appli(chemin.stem, nwa=chemin)
        self.applis.append(appli)
        return appli

    def retirer(self, index: int) -> None:
        del self.applis[index]

    def vider(self) -> None:
        self.applis.clear()

    def deplacer(self, index: int, delta: int) -> int:
        cible = index + delta
        if not 0 <= cible < len(self.applis):
            return index
        self.applis[index], self.applis[cible] = self.applis[cible], self.applis[index]
        return cible

    def total(self) -> int:
        return sum(a.taille for a in self.applis)

    # --------------------------------------------------------------- presets
    def exporter_preset(self, chemin: Path) -> None:
        """Archive la liste, ses .nwa et toutes ses données externes."""
        if not self.applis:
            raise ErreurListe("Ajoutez au moins une appli avant d’exporter un preset.")
        if len(self.applis) > 500:
            raise ErreurListe("Un preset ne peut pas contenir plus de 500 applications.")
        if not self.telecharger():
            raise ErreurListe("Un fichier .nwa du catalogue n’a pas pu être téléchargé.")

        manifeste = {"format": "numworks-installateur-preset", "version": 1, "applis": []}
        fichiers = []
        for index, appli in enumerate(self.applis):
            if not appli.nwa or not appli.nwa.is_file():
                raise ErreurListe(f"Fichier .nwa introuvable pour {appli.libelle()}.")
            if appli.donnees and not appli.donnees.is_file():
                raise ErreurListe(f"Données introuvables pour {appli.libelle()}.")

            nwa_archive = f"fichiers/{index:04d}-application.nwa"
            data_archive = f"fichiers/{index:04d}-donnees{appli.donnees.suffix}" if appli.donnees else None
            manifeste["applis"].append(
                {
                    "nom": appli.nom,
                    "emulateur": appli.emul["id"] if appli.emul else None,
                    "nwa": nwa_archive,
                    "nom_nwa": appli.nwa.name,
                    "donnees": data_archive,
                    "nom_donnees": appli.donnees.name if appli.donnees else None,
                }
            )
            fichiers.append((appli.nwa, nwa_archive))
            if appli.donnees:
                fichiers.append((appli.donnees, data_archive))

        chemin.parent.mkdir(parents=True, exist_ok=True)
        destination = chemin.resolve()
        if any(source.resolve() == destination for source, _ in fichiers):
            raise ErreurListe("Le preset ne peut pas remplacer un fichier de la liste.")
        temporaire = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="preset-", suffix=".tmp", dir=chemin.parent, delete=False
            ) as fichier_temp:
                temporaire = Path(fichier_temp.name)
            with zipfile.ZipFile(temporaire, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "preset.json",
                    json.dumps(manifeste, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                for source, destination_archive in fichiers:
                    archive.write(source, destination_archive)
            temporaire.replace(chemin)
        finally:
            if temporaire and temporaire.exists():
                temporaire.unlink()
        self.log(f"Preset exporté : {chemin} ({len(self.applis)} appli(s)).")

    def importer_preset(self, chemin: Path) -> None:
        """Charge un preset validé, puis remplace la liste actuelle."""
        dossier = None
        try:
            with zipfile.ZipFile(chemin, "r") as archive:
                noms = archive.namelist()
                if len(noms) != len(set(noms)):
                    raise ErreurListe("Le preset contient des noms de fichiers en double.")
                infos = {info.filename: info for info in archive.infolist()}
                if "preset.json" not in infos or infos["preset.json"].file_size > 1024 * 1024:
                    raise ErreurListe("Le fichier preset.json est absent ou trop volumineux.")
                if sum(info.file_size for info in infos.values()) > 128 * 1024 * 1024:
                    raise ErreurListe("Le preset dépasse la taille maximale de 128 Mo.")
                manifeste = json.loads(archive.read("preset.json").decode("utf-8"))
                if (
                    manifeste.get("format") != "numworks-installateur-preset"
                    or manifeste.get("version") != 1
                    or not isinstance(manifeste.get("applis"), list)
                    or not manifeste["applis"]
                    or len(manifeste["applis"]) > 500
                ):
                    raise ErreurListe("Format de preset non reconnu ou liste vide.")

                entrees = []
                for entree in manifeste["applis"]:
                    if not isinstance(entree, dict):
                        raise ErreurListe("Une entrée du preset est invalide.")
                    nwa_nom = self._nom_fichier_preset(entree.get("nwa"), infos)
                    data_nom = entree.get("donnees")
                    if data_nom is not None:
                        data_nom = self._nom_fichier_preset(data_nom, infos)
                    identifiant = entree.get("emulateur")
                    emul = emul_par_id(identifiant) if identifiant is not None else None
                    if identifiant is not None and emul is None:
                        raise ErreurListe(f"Émulateur inconnu dans le preset : {identifiant}")
                    nom_nwa = self._nom_local_preset(entree.get("nom_nwa"), ".nwa")
                    if not nom_nwa.lower().endswith(".nwa"):
                        raise ErreurListe("Un fichier d’application du preset n’a pas l’extension .nwa.")
                    nom_data = (
                        self._nom_local_preset(entree.get("nom_donnees"), ".bin")
                        if data_nom
                        else None
                    )
                    entrees.append((entree, nwa_nom, data_nom, emul, nom_nwa, nom_data))

                IMPORTS.mkdir(parents=True, exist_ok=True)
                dossier = Path(tempfile.mkdtemp(prefix="preset-", dir=IMPORTS))
                nouvelles = []
                for index, (entree, nwa_archive, data_archive, emul, nom_nwa, nom_data) in enumerate(entrees):
                    nwa_path = dossier / f"{index:04d}-{nom_nwa}"
                    nwa_path.write_bytes(archive.read(nwa_archive))
                    appli = Appli(str(entree.get("nom") or Path(nom_nwa).stem), nwa=nwa_path, emul=emul)
                    if data_archive:
                        data_path = dossier / f"{index:04d}-{nom_data}"
                        data_path.write_bytes(archive.read(data_archive))
                        appli.donnees = data_path
                    nouvelles.append(appli)
        except ErreurListe:
            if dossier:
                shutil.rmtree(dossier, ignore_errors=True)
            raise
        except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError) as err:
            if dossier:
                shutil.rmtree(dossier, ignore_errors=True)
            raise ErreurListe(f"Impossible de lire le preset : {err}") from err

        self.applis = nouvelles
        self.log(f"Preset importé : {chemin} ({len(nouvelles)} appli(s)).")

    @staticmethod
    def _nom_fichier_preset(nom: object, infos: dict) -> str:
        if not isinstance(nom, str):
            raise ErreurListe("Un fichier référencé dans le preset est invalide.")
        chemin = PurePosixPath(nom)
        if chemin.is_absolute() or ".." in chemin.parts or "\\" in nom or nom not in infos:
            raise ErreurListe("Le preset référence un chemin de fichier invalide.")
        return nom

    @staticmethod
    def _nom_local_preset(nom: object, suffixe_defaut: str) -> str:
        if not isinstance(nom, str) or not nom.strip():
            nom = f"fichier{suffixe_defaut}"
        nom = PurePosixPath(nom.replace("\\", "/")).name
        nom = "".join(c for c in nom if c.isalnum() or c in " ._-()")
        return nom.strip(" .") or f"fichier{suffixe_defaut}"

    # ------------------------------------------------------------ préparation
    def telecharger(self) -> bool:
        """Récupère les .nwa du catalogue encore absents du cache."""
        with self._verrou_dl:
            return self._telecharger()

    def _telecharger(self) -> bool:
        CACHE.mkdir(parents=True, exist_ok=True)
        ok = True
        for appli in list(self.applis):
            if appli.nwa and appli.nwa.is_file():
                continue
            if not appli.emul:
                ok = False
                continue
            dest = CACHE / appli.emul["fichier"]
            self.log(f"Téléchargement {appli.emul['url']} …")
            try:
                urllib.request.urlretrieve(appli.emul["url"], dest)
            except (urllib.error.URLError, OSError) as err:
                ok = False
                self.log(f"Échec pour {appli.libelle()} : {err}")
                continue
            appli.nwa = dest
            self.log(f"Enregistré : {dest} ({fmt_taille(dest.stat().st_size)})")
        return ok

    def verifier(self) -> None:
        """Lève ErreurListe si la liste ne peut pas être assemblée."""
        if not self.applis:
            raise ErreurListe("Ajoutez au moins une appli à la liste.")
        sans_rom = [a.libelle() for a in self.applis if a.besoin_rom() and not a.donnees]
        if sans_rom:
            raise ErreurListe(
                "Ces émulateurs ne peuvent pas être assemblés sans ROM : "
                + ", ".join(sans_rom)
            )
        for appli in self.applis:
            if appli.donnees and not appli.donnees.is_file():
                raise ErreurListe(f"Données introuvables pour {appli.libelle()}.")

    def _entrees(self) -> List[Tuple[str, Optional[str]]]:
        return [
            (str(a.nwa), str(a.donnees) if a.donnees else None) for a in self.applis
        ]

    def commande(self, essai: bool) -> List[str]:
        """Commande d'envoi groupé, ou de secours si un seul .nwa et pas de npm."""
        if trouver_npm():
            try:
                if essai:
                    return commande_essai(
                        RUNTIME, MANIFESTE, self._entrees(), IMAGE_ESSAI, self.log
                    )
                return commande_multi(RUNTIME, MANIFESTE, self._entrees(), self.log)
            except (ErreurNwlink, subprocess.SubprocessError, OSError) as err:
                self.log(f"Envoi groupé indisponible : {err}")
        if essai or len(self.applis) > 1:
            raise ErreurListe(
                "Node.js (npm) est nécessaire pour assembler plusieurs applis : "
                "installez la version LTS depuis nodejs.org."
            )
        npx = trouver_npx()
        if not npx:
            raise ErreurListe("Ni npm ni npx : installez Node.js LTS (nodejs.org).")
        seule = self.applis[0]
        return commande_simple(
            npx, str(seule.nwa), str(seule.donnees) if seule.donnees else None
        )

    # ------------------------------------------------------------ installation
    def preparer(self, essai: bool) -> List[str]:
        """Télécharge, contrôle la taille puis renvoie la commande à lancer."""
        self.verifier()
        if not self.telecharger():
            raise ErreurListe("Une appli n’a pas pu être téléchargée.")
        manquants = [a.libelle() for a in self.applis if not (a.nwa and a.nwa.is_file())]
        if manquants:
            raise ErreurListe("Fichiers .nwa introuvables : " + ", ".join(manquants))

        total = self.total()
        self.log(f"{len(self.applis)} appli(s), taille totale : {fmt_taille(total)}")
        if total > LIMITE_FLASH_MO * 1024 * 1024:
            raise ErreurListe(
                "Retirez des applis : la zone applis externes fait environ 8 Mo."
            )
        if total > LIMITE_SITE_MO * 1024 * 1024:
            self.log(
                "Au-delà de ~2,5 Mo : le site NumWorks refuse souvent sans Nwagra. "
                "nwlink utilise déjà la plage élargie."
            )
        return self.commande(essai)

    def executer(self, cmd: List[str], essai: bool) -> bool:
        """Lance nwlink et journalise le résultat."""
        self.log("Commande : " + " ".join(cmd))
        if not essai:
            self.log(
                "Branchez la calculatrice, laissez-la allumée, "
                "fermez les autres onglets USB…"
            )
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(RACINE),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            self.log("Délai dépassé (15 min).")
            return False
        except OSError as err:
            self.log(f"Impossible de lancer nwlink : {err}")
            return False

        sortie = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if sortie:
            self.log(sortie)
        if "_eadk_external_data_start" in sortie:
            self.log(
                "Une appli de la liste réclame des données externes : "
                "choisissez sa ROM / ses données."
            )
        if proc.returncode == 0:
            if essai:
                self.log(f"Essai réussi : image assemblée dans {IMAGE_ESSAI}.")
            else:
                self.log("Terminé. Sur la calculatrice : applis externes (hors mode examen).")
            return True
        self.log(f"Échec (code {proc.returncode}).")
        self.log(
            "Pistes : câble data, RESET au dos, un seul Chrome/nwlink, "
            "pilote WinUSB (comme pour my.numworks.com), Node.js LTS."
        )
        return False

    def installer(self, essai: bool) -> bool:
        return self.executer(self.preparer(essai), essai)
