"""
build_installer.py
==================
Compilation ultra-légère multi-OS de FTPStudio avec support du mode serveur.
Exécution : python build_installer.py
"""

import os
import platform
import shutil
import subprocess
import sys

APP_NAME = "FTPStudio"
ENTRY_POINT = "main.py"

def clean():
    for f in ("build", "dist"):
        if os.path.exists(f):
            shutil.rmtree(f)

def build():
    clean()
    current_os = platform.system()
    print(f"🚀 Compilation de {APP_NAME} pour {current_os}...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", APP_NAME,
        "--collect-all", "customtkinter",
        "--collect-all", "pyftpdlib",
        ENTRY_POINT
    ]

    res = subprocess.run(cmd)
    if res.returncode != 0:
        print("❌ Échec de la compilation.")
        sys.exit(1)

    # Archivage
    if current_os == "Linux":
        archive = f"{APP_NAME}-Linux.tar.gz"
        subprocess.run(["tar", "-czf", archive, "-C", "dist", APP_NAME])
    else:
        archive = f"{APP_NAME}-{current_os}.zip"
        shutil.make_archive(f"{APP_NAME}-{current_os}", "zip", "dist", APP_NAME)

    print(f"\n✅ Succès ! Archive créée : {archive}")

if __name__ == "__main__":
    build()