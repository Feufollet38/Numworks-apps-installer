"""Émulateurs NWA publics (Nwagyu / forks Yaya-Cout). Pas de ROM propriétaire."""

EMULATEURS = [
    {
        "id": "peanutgb",
        "nom": "Peanut-GB — Game Boy",
        "roms": (".gb",),
        "fichier": "peanutgb.nwa",
        "url": "https://codeberg.org/Yaya-Cout/peanutgb/releases/download/v1.2.2/peanutgb.nwa",
    },
    {
        "id": "peanutgbc",
        "nom": "Peanut-GBC — Game Boy Color",
        "roms": (".gbc", ".gb"),
        "fichier": "peanutgbc.nwa",
        "url": "https://codeberg.org/Yaya-Cout/peanutgbc/releases/download/v1.1.1/peanutgbc.nwa",
    },
    {
        "id": "nofrendo",
        "nom": "Nofrendo — NES",
        "roms": (".nes",),
        "fichier": "nofrendo.nwa",
        "url": "https://codeberg.org/Yaya-Cout/nofrendo/releases/download/v1.2.3/nofrendo.nwa",
    },
]

AUTRE_NWA = "Autre fichier .nwa (choisi à la main)"


def emul_pour_rom(chemin: str):
    ext = chemin.lower()
    for e in EMULATEURS:
        if any(ext.endswith(s) for s in e["roms"]):
            return e
    return None
