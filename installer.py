#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Installateur NumWorks (fenêtre) : plusieurs applis NWA en un seul envoi."""

from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path
from typing import Callable, List
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from catalogue import AUTRE_NWA, EMULATEURS, emul_pour_rom
from noyau import ErreurListe, Liste, fmt_taille

RACINE = Path(__file__).resolve().parent
NWAGRA_HTML = RACINE / "nwagra.html"
APPS_URL = "https://my.numworks.com/apps"
NWAGYU = "https://nwagyu.org/fr/guide/"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("NumWorks — installer plusieurs applis d’un coup")
        self.minsize(760, 640)
        self.geometry("980x720")
        self.choix_emul = tk.StringVar(value=EMULATEURS[0]["nom"])
        self.total_txt = tk.StringVar(value="Liste vide.")
        self.liste = Liste(self._log_fil)
        self._busy = False
        self._build()

    @property
    def applis(self):
        return self.liste.applis

    # ---------------------------------------------------------------- interface
    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        ttk.Label(
            self,
            text=(
                "Ajoutez autant d’applis que voulu à la liste, associez-leur une ROM "
                "si besoin, puis installez tout en une seule fois."
            ),
            wraplength=840,
        ).pack(anchor="w", **pad)

        f1 = ttk.LabelFrame(self, text="1. Ajouter des applis")
        f1.pack(fill="x", **pad)
        ttk.Combobox(
            f1,
            textvariable=self.choix_emul,
            values=[e["nom"] for e in EMULATEURS] + [AUTRE_NWA],
            state="readonly",
            width=44,
        ).pack(side="left", padx=8, pady=8, fill="x", expand=True)
        ttk.Button(f1, text="Ajouter à la liste", command=self.ajouter_catalogue).pack(
            side="left", padx=8, pady=8
        )
        ttk.Button(f1, text="Ajouter des fichiers .nwa…", command=self.ajouter_fichiers).pack(
            side="left", padx=8, pady=8
        )

        f2 = ttk.LabelFrame(self, text="2. Liste à installer")
        f2.pack(fill="both", expand=True, **pad)
        self.tableau = ttk.Treeview(
            f2,
            columns=("appli", "nwa", "donnees", "taille"),
            show="headings",
            height=7,
            selectmode="extended",
        )
        for col, titre, largeur in (
            ("appli", "Appli", 210),
            ("nwa", "Fichier .nwa", 230),
            ("donnees", "ROM / données", 230),
            ("taille", "Taille", 90),
        ):
            self.tableau.heading(col, text=titre)
            self.tableau.column(col, width=largeur, anchor="w")
        self.tableau.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        f3 = ttk.Frame(f2)
        f3.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(f3, text="ROM / données…", command=self.choisir_rom).pack(side="left")
        ttk.Button(f3, text="Monter", command=lambda: self.deplacer(-1)).pack(side="left", padx=6)
        ttk.Button(f3, text="Descendre", command=lambda: self.deplacer(1)).pack(side="left")
        ttk.Button(f3, text="Retirer", command=self.retirer).pack(side="left", padx=6)
        ttk.Button(f3, text="Vider la liste", command=self.vider).pack(side="left")
        self.btn_export_preset = ttk.Button(
            f3, text="Exporter preset…", command=self.exporter_preset
        )
        self.btn_export_preset.pack(side="left", padx=(12, 4))
        self.btn_import_preset = ttk.Button(
            f3, text="Importer preset…", command=self.importer_preset
        )
        self.btn_import_preset.pack(side="left", padx=4)
        ttk.Label(f3, textvariable=self.total_txt).pack(side="right")

        f4 = ttk.Frame(self)
        f4.pack(fill="x", **pad)
        self.btn_ok = ttk.Button(
            f4, text="Valider et tout installer sur la calculatrice", command=self.installer
        )
        self.btn_ok.pack(side="left")
        ttk.Button(f4, text="Essai sans calculatrice", command=self.essayer).pack(
            side="left", padx=8
        )
        ttk.Button(f4, text="Ouvrir Nwagra (site NumWorks)", command=self.ouvrir_nwagra).pack(
            side="left", padx=8
        )
        ttk.Button(f4, text="Catalogue Nwagyu", command=lambda: webbrowser.open(NWAGYU)).pack(
            side="left"
        )

        ttk.Label(
            self,
            text=(
                "L’envoi utilise nwlink (Node.js) et écrit toutes les applis de la liste "
                "en un seul flash : la zone « applis externes » de la calculatrice est "
                "remplacée par cette liste, donc mettez-y tout ce que vous voulez garder. "
                "Branchez la NumWorks en USB, un seul logiciel à la fois. Les ROM doivent "
                "être vos dumps (pas de fichiers protégés ici)."
            ),
            wraplength=840,
        ).pack(anchor="w", **pad)

        self.log = tk.Text(self, height=12, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._log(
            "Prêt. Installez Node.js (LTS) si npm est introuvable : https://nodejs.org/\n"
            "Chrome doit déjà pouvoir parler à la calculatrice (my.numworks.com/apps).\n"
        )

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg)
        if not msg.endswith("\n"):
            self.log.insert("end", "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.update_idletasks()

    def _log_fil(self, msg: str) -> None:
        """Journalisation depuis un fil de fond : repasse par la boucle Tk."""
        if threading.current_thread() is threading.main_thread():
            self._log(msg)
        else:
            self.after(0, self._log, msg)

    # -------------------------------------------------------------- liste d’applis
    def emul_courant(self):
        nom = self.choix_emul.get()
        for e in EMULATEURS:
            if e["nom"] == nom:
                return e
        return None

    def rafraichir(self) -> None:
        self.tableau.delete(*self.tableau.get_children())
        for i, appli in enumerate(self.applis):
            self.tableau.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    appli.libelle(),
                    appli.nwa.name if appli.nwa else "à télécharger",
                    appli.donnees.name if appli.donnees else "—",
                    fmt_taille(appli.taille) if appli.taille else "—",
                ),
            )
        if not self.applis:
            self.total_txt.set("Liste vide.")
        else:
            self.total_txt.set(
                f"{len(self.applis)} appli(s) — total {fmt_taille(self.liste.total())}"
            )

    def selection(self) -> List[int]:
        return sorted(int(iid) for iid in self.tableau.selection())

    def ajouter_catalogue(self) -> None:
        if self._busy:
            return
        e = self.emul_courant()
        if not e:
            self.ajouter_fichiers()
            return
        appli = self.liste.ajouter_emulateur(e["id"])
        self.rafraichir()
        if not appli.nwa and not self._busy:
            self._run_bg(self._telecharger_et_rafraichir)

    def ajouter_fichiers(self) -> None:
        if self._busy:
            return
        chemins = filedialog.askopenfilenames(
            title="Fichiers application NumWorks (sélection multiple possible)",
            filetypes=[("Applis NWA", "*.nwa"), ("Tous", "*.*")],
        )
        for p in chemins:
            self.liste.ajouter_fichier(Path(p))
        if chemins:
            self.rafraichir()

    def choisir_rom(self) -> None:
        if self._busy:
            return
        indices = self.selection()
        if len(indices) != 1:
            messagebox.showinfo(
                "Sélection",
                "Sélectionnez une seule appli de la liste avant de choisir sa ROM.",
            )
            return
        p = filedialog.askopenfilename(
            title="ROM ou données externes",
            filetypes=[
                ("ROMs et données", "*.gb *.gbc *.nes *.ch8 *.png *.bin *.txt"),
                ("Tous", "*.*"),
            ],
        )
        if not p:
            return
        appli = self.applis[indices[0]]
        appli.donnees = Path(p)
        hint = emul_pour_rom(p)
        if hint and not appli.emul:
            self._log(f"ROM {Path(p).suffix} → émulateur conseillé : {hint['nom']}")
        self.rafraichir()

    def retirer(self) -> None:
        if self._busy:
            return
        for i in reversed(self.selection()):
            self.liste.retirer(i)
        self.rafraichir()

    def vider(self) -> None:
        if self._busy:
            return
        self.liste.vider()
        self.rafraichir()

    def exporter_preset(self) -> None:
        if self._busy:
            return
        chemin = filedialog.asksaveasfilename(
            title="Exporter le preset de la liste",
            defaultextension=".nwpreset",
            filetypes=[("Preset NumWorks", "*.nwpreset"), ("Archives ZIP", "*.zip")],
        )
        if chemin:
            self._run_bg(lambda: self._exporter_preset(Path(chemin)))

    def _exporter_preset(self, chemin: Path) -> None:
        try:
            self.liste.exporter_preset(chemin)
        except ErreurListe as err:
            self.after(0, messagebox.showerror, "Export du preset", str(err))
            return
        except OSError as err:
            self.after(0, messagebox.showerror, "Export du preset", str(err))
            return
        self.after(
            0,
            lambda: messagebox.showinfo(
                "Export du preset", f"Preset enregistré dans :\n{chemin}"
            ),
        )

    def importer_preset(self) -> None:
        if self._busy:
            return
        chemin = filedialog.askopenfilename(
            title="Importer un preset NumWorks",
            filetypes=[("Presets NumWorks", "*.nwpreset *.zip"), ("Tous", "*.*")],
        )
        if not chemin:
            return
        if self.applis and not messagebox.askyesno(
            "Remplacer la liste ?",
            "L’import du preset remplacera la liste actuelle. Continuer ?",
        ):
            return
        self._run_bg(lambda: self._importer_preset(Path(chemin)))

    def _importer_preset(self, chemin: Path) -> None:
        try:
            self.liste.importer_preset(chemin)
        except ErreurListe as err:
            self.after(0, messagebox.showerror, "Import du preset", str(err))
            return
        except OSError as err:
            self.after(0, messagebox.showerror, "Import du preset", str(err))
            return
        self.after(0, self.rafraichir)
        self.after(
            0,
            lambda: messagebox.showinfo(
                "Import du preset", f"Preset importé : {len(self.applis)} appli(s)."
            ),
        )

    def deplacer(self, delta: int) -> None:
        if self._busy:
            return
        indices = self.selection()
        if len(indices) != 1:
            return
        cible = self.liste.deplacer(indices[0], delta)
        self.rafraichir()
        self.tableau.selection_set(str(cible))

    def _telecharger_et_rafraichir(self) -> None:
        self.liste.telecharger()
        self.after(0, self.rafraichir)

    def ouvrir_nwagra(self) -> None:
        webbrowser.open(NWAGRA_HTML.as_uri())
        webbrowser.open(APPS_URL)

    # ------------------------------------------------------------- installation
    def installer(self) -> None:
        self._lancer(essai=False)

    def essayer(self) -> None:
        self._lancer(essai=True)

    def _lancer(self, essai: bool) -> None:
        if self._busy:
            return
        try:
            self.liste.verifier()
        except ErreurListe as err:
            messagebox.showerror("Liste incomplète", str(err))
            return
        self._run_bg(lambda: self._envoyer(essai))

    def _envoyer(self, essai: bool) -> None:
        try:
            ok = self.liste.installer(essai)
        except ErreurListe as err:
            self._log_fil(str(err))
            self.after(0, lambda: messagebox.showerror("Installation", str(err)))
            return
        self.after(0, self.rafraichir)
        titre = "Essai" if essai else "Installation"
        if ok:
            message = (
                f"Les {len(self.applis)} appli(s) tiennent ensemble : "
                "vous pouvez brancher la calculatrice et installer."
                if essai
                else f"Envoi terminé : {len(self.applis)} appli(s)."
            )
            self.after(0, lambda: messagebox.showinfo(titre, message))
        else:
            self.after(
                0, lambda: messagebox.showerror(titre, "nwlink a échoué. Voir le journal.")
            )

    def _run_bg(self, fn: Callable[[], None]) -> None:
        self._busy = True
        self.btn_ok.state(["disabled"])
        self.btn_export_preset.state(["disabled"])
        self.btn_import_preset.state(["disabled"])

        def wrap() -> None:
            try:
                fn()
            finally:
                self._busy = False
                self.after(0, self._finir_tache)

        threading.Thread(target=wrap, daemon=True).start()

    def _finir_tache(self) -> None:
        self.btn_ok.state(["!disabled"])
        self.btn_export_preset.state(["!disabled"])
        self.btn_import_preset.state(["!disabled"])


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
