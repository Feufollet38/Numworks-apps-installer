"""Envoi de plusieurs applis NWA en une seule opération, via nwlink.

La ligne de commande officielle de nwlink ne sait installer qu'un seul .nwa à la
fois, et chaque envoi réécrit toute la zone « applis externes » de la
calculatrice : installer deux applis l'une après l'autre ne laisse que la
dernière. Le moteur interne de nwlink, lui, sait empaqueter plusieurs applis
(classe « bundle ») et les écrire en un seul flash.

Ce module installe nwlink en local, ajoute à son interface une commande
« install-multi » qui lit un manifeste JSON, et fournit la commande à lancer.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

NWLINK_VERSION = "0.0.19"
NWLINK_SPEC = f"nwlink@{NWLINK_VERSION}"
COMMANDE_MULTI = "install-multi"
ANCRE = r"[\w$]+\.command\(\"nwa-elf\"\)"

Journal = Callable[[str], None]


class ErreurNwlink(RuntimeError):
    """nwlink est indisponible ou son code n'a pas pu être adapté."""


def trouver_npm() -> Optional[str]:
    return shutil.which("npm") or shutil.which("npm.cmd")


def trouver_npx() -> Optional[str]:
    return shutil.which("npx") or shutil.which("npx.cmd")


def _executer(cmd: Sequence[str], cwd: Path, log: Journal) -> None:
    log("Commande : " + " ".join(cmd))
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        shell=False,
    )
    sortie = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if sortie:
        log(sortie)
    if proc.returncode != 0:
        raise ErreurNwlink(f"« {cmd[0]} » a renvoyé {proc.returncode}.")


def installer_nwlink(racine_runtime: Path, log: Journal) -> Path:
    """Installe nwlink dans racine_runtime et renvoie son dist/index.js."""
    index = racine_runtime / "node_modules" / "nwlink" / "dist" / "index.js"
    manifeste = racine_runtime / "node_modules" / "nwlink" / "package.json"
    if index.is_file() and manifeste.is_file():
        try:
            version = json.loads(manifeste.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            version = None
        if version == NWLINK_VERSION:
            return index

    npm = trouver_npm()
    if not npm:
        raise ErreurNwlink("npm (Node.js) est introuvable.")
    racine_runtime.mkdir(parents=True, exist_ok=True)
    log(f"Installation de {NWLINK_SPEC} dans {racine_runtime} …")
    _executer(
        [npm, "install", "--no-audit", "--no-fund", "--loglevel", "error", NWLINK_SPEC],
        racine_runtime,
        log,
    )
    if not index.is_file():
        raise ErreurNwlink("nwlink installé mais dist/index.js est introuvable.")
    return index


def _noms_internes(source: str) -> Tuple[str, str, str, str, str]:
    """Retrouve les identifiants minifiés dont la commande ajoutée a besoin."""
    action = re.search(
        r"([\w$]+)=([\w$]+)\([\w$]+,[\w$]+\),\(([\w$]+)=new ([\w$]+)\)\.push\(\1\),[\w$]+=new ([\w$]+),",
        source,
    )
    programme = re.search(r"([\w$]+)\.command\(\"install-nwa\"\)", source)
    barre = re.search(r"new ([\w$]+)\.SingleBar\(", source)
    ancre = re.search(ANCRE, source)
    if not (action and programme and barre and ancre):
        raise ErreurNwlink(
            "Le code de nwlink ne correspond pas à celui attendu "
            f"(version {NWLINK_VERSION})."
        )
    return (
        programme.group(1),
        action.group(2),  # fabrique d'appli à partir d'un fichier .nwa
        action.group(4),  # classe « bundle » d'applis
        action.group(5),  # classe calculatrice
        barre.group(1),  # module cli-progress
    )


def _code_commande(prog: str, appli: str, bundle: str, calc: str, progress: str) -> str:
    return (
        f'{prog}.command("{COMMANDE_MULTI}")'
        '.description("Install several NWA apps in a single flash")'
        '.argument("<manifest.json>","JSON list of {nwa, data} entries")'
        '.option("--dry-run <output.bin>","Link every app into one image, without a calculator")'
        ".action(function(manifeste,options){"
        'var entrees=JSON.parse(require("fs").readFileSync(manifeste,"utf8"));'
        f"var lot=new {bundle}();"
        "entrees.forEach(function(entree){"
        f"lot.push({appli}(entree.nwa,entree.data?{{externalData:entree.data}}:{{}}));"
        "});"
        "if(options.dryRun){"
        "return lot.flatBin({flashStart:2415919104,flashLength:8388608,"
        "ramStart:536870912,ramLength:262144,trampolineStart:2415984688})"
        '.then(function(image){require("fs").writeFileSync(options.dryRun,image);'
        'console.log("Image de "+image.length+" octets pour "+entrees.length+" appli(s).");});'
        "}"
        f"return new {calc}().singleConnectAndExtractInfos(!0).then(function(infos){{"
        f'var barre=new {progress}.SingleBar({{stopOnComplete:!0,'
        'format:"Upload [{bar}] {percentage}% | ETA: {eta}s"});'
        "barre.start(1,0);"
        "return lot.upload(infos,function(p){barre.update(p);});"
        "});"
        "}),"
    )


def preparer_multi(racine_runtime: Path, log: Journal) -> Path:
    """Renvoie le point d'entrée nwlink enrichi de la commande install-multi."""
    index = installer_nwlink(racine_runtime, log)
    patche = index.with_name("index_multi.js")
    source = index.read_text(encoding="utf-8", errors="strict")
    if patche.is_file():
        deja = patche.read_text(encoding="utf-8", errors="ignore")
        if f'command("{COMMANDE_MULTI}")' in deja and len(deja) > len(source):
            return patche

    prog, appli, bundle, calc, progress = _noms_internes(source)
    ancre = re.search(ANCRE, source)
    assert ancre is not None  # garanti par _noms_internes
    injection = _code_commande(prog, appli, bundle, calc, progress)
    patche.write_text(
        source[: ancre.start()] + injection + source[ancre.start() :],
        encoding="utf-8",
    )
    log(f"Commande {COMMANDE_MULTI} ajoutée à nwlink ({patche.name}).")
    return patche


def ecrire_manifeste(
    chemin: Path, applis: Sequence[Tuple[str, Optional[str]]]
) -> Path:
    entrees = [{"nwa": nwa, "data": data or None} for nwa, data in applis]
    chemin.write_text(json.dumps(entrees, ensure_ascii=False), encoding="utf-8")
    return chemin


def commande_multi(
    racine_runtime: Path,
    manifeste: Path,
    applis: Sequence[Tuple[str, Optional[str]]],
    log: Journal,
) -> List[str]:
    """Prépare le manifeste et renvoie la commande d'installation groupée."""
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        raise ErreurNwlink("Node.js (node) est introuvable.")
    entree = preparer_multi(racine_runtime, log)
    ecrire_manifeste(manifeste, applis)
    return [
        node,
        "-e",
        "require(process.argv[1])(process.argv);",
        str(entree.resolve()),
        COMMANDE_MULTI,
        str(manifeste.resolve()),
    ]


def commande_essai(
    racine_runtime: Path,
    manifeste: Path,
    applis: Sequence[Tuple[str, Optional[str]]],
    image: Path,
    log: Journal,
) -> List[str]:
    """Même assemblage, mais écrit l'image dans un fichier au lieu de la flasher."""
    cmd = commande_multi(racine_runtime, manifeste, applis, log)
    cmd.extend(["--dry-run", str(image.resolve())])
    return cmd


def commande_simple(npx: str, nwa: str, donnees: Optional[str]) -> List[str]:
    """Secours : la commande officielle, limitée à une seule appli."""
    cmd = [npx, "--yes", "--", NWLINK_SPEC, "install-nwa"]
    if donnees:
        cmd.extend(["--external-data", donnees])
    cmd.append(nwa)
    return cmd
