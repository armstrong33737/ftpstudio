cat << 'EOF' > README.md
# 🌐 FTPStudio

> **Partagez et détectez des fichiers sur votre réseau local en un clic (Linux, Windows, macOS).**

FTPStudio simplifie le transfert de fichiers en réseau local : il détecte automatiquement les ordinateurs partageant des dossiers et permet d'y accéder directement dans **l'explorateur de fichiers natif de votre système d'exploitation** (Fichiers/Nautilus sous Linux, Explorateur Windows, Finder sous macOS) ou via un **QR Code sur smartphone**.

---

## ⚡ Pourquoi FTPStudio ?

- **Conçu pour tous (Zéro configuration)** : plus besoin de chercher, taper ou comprendre les adresses IP, les masques CIDR ou les numéros de ports. L'application calcule tout automatiquement.
- **Noms d'ordinateurs conviviaux** : identifiez immédiatement vos machines par leur vrai nom (*« PC-Bureau »*, *« PC-Salon »*) plutôt que par une simple adresse IP froide.
- **Ouverture native dans votre OS** : les fichiers s'ouvrent dans votre gestionnaire de bureau habituel avec le glisser-déposer, les raccourcis et le cache natif de votre ordinateur.
- **Partage mobile instantané** : générez un QR Code scannable par n'importe quel téléphone (iPhone, Android) pour télécharger vos fichiers depuis un simple navigateur web sans rien installer.
- **Code source autonome en fichier unique** : toute l'application tient dans un seul fichier propre (`main.py`).

---

## 🚀 Fonctionnalités Principales

### 🔍 1. Détection Réseau à Large Spectre
- **Balayage automatique intelligent** : analyse automatique du sous-réseau local sur une plage étendue :
  - Ports standard & alternatifs : `20 à 30` (FTP, SFTP/SSH, etc.)
  - Ports alternatifs FTPStudio : `2121 à 2130`
  - Ports SFTP étendus : `2221 à 2230`
  - Ports Web & Micro-serveurs : `8000 à 8010` et `8080 à 8095`
  - Ports sécurisés : `80`, `990`
- **Moteur multithread ultra-rapide (250 flux parallèles)** : parcourt des milliers de combinaisons en quelques secondes.
- **Découverte instantanée mDNS / Zeroconf** : deux machines équipées de FTPStudio s'affichent mutuellement en **0,1 seconde** sans même attendre la fin du scan.
- **⭐ Système de Favoris** : épinglez vos serveurs réguliers (NAS, box, ordinateurs de travail) pour les retrouver en tête de liste à chaque démarrage.

### 📁 2. Partage de Fichiers Double-Mode
- **Mode Ordinateurs (FTP)** : dédié à une ouverture fluide dans Nautilus, Dolphin ou l'Explorateur Windows.
- **Mode Smartphones & Web (HTTP)** : transforme votre dossier en un mini-cloud accessible depuis n'importe quel navigateur (Chrome, Safari, Firefox) avec prévisualisation et téléchargement direct.
- **QR Code en direct** : scannez le code affiché à l'écran avec l'appareil photo de votre téléphone pour accéder instantanément aux fichiers partagés.
- **Nom de partage personnalisé** : donnez un nom clair à votre partage (par défaut, le nom de votre PC).
- **Sécurité optionnelle** : verrouillage par mot de passe activable en une case à cocher.

### 🛡️ 3. Ergonomie & Contrôle Propre
- **Raccourci universel `Ctrl + Q` (ou `Cmd + Q`)** : quitte instantanément l'application et arrête tous les partages.
- **Bouton Quitter direct (✕)** : fermeture sécurisée avec dialogue de confirmation si un partage est encore en cours.
- **Thèmes Sombre 🌙 et Clair ☀️** : bascule esthétique instantanée.

---

## 📦 Intégrations par Système d'Exploitation

| Système d'exploitation | Gestionnaire de fichiers ciblé | Mode Ordinateur (FTP) | Mode Smartphone (Web) |
| :--- | :--- | :---: | :---: |
| **Ubuntu / Debian / Fedora** | **GNOME Fichiers (Nautilus)** | ✅ Natif (GVFS) | ✅ Navigateur Web / QR Code |
| **KDE Plasma** | **Dolphin** | ✅ Natif (KIO) | ✅ Navigateur Web / QR Code |
| **Linux Mint / XFCE / MATE** | **Nemo / Thunar / Caja** | ✅ Natif (GVFS) | ✅ Navigateur Web / QR Code |
| **Windows 10 / 11** | **Explorateur Windows** | ✅ Natif | ✅ Navigateur Web / QR Code |
| **macOS** | **Finder** | ✅ Natif | ✅ Navigateur Web / QR Code |

---

## 🛠️ Installation & Démarrage

### Prérequis
- **Python 3.10 ou supérieur**
- Sur Linux (Ubuntu/Debian), assurez-vous d'avoir Tkinter installé :
  sudo apt-get update && sudo apt-get install -y python3-tk

### 1. Cloner le projet
git clone https://github.com/votre-utilisateur/ftpstudio.git
cd ftpstudio

### 2. Installer les dépendances
pip install -r requirements.txt

### 3. Lancer l'application
python3 main.py

---

## 🔨 Compilation Locale (Binaires autonomes)

Pour créer un binaire exécutable sans dépendance Python pour votre OS :

python build_installer.py

Les exécutables et leurs archives prêtes à l'emploi seront créés dans le dossier `dist/` :
- **Linux** : `dist/FTPStudio/` et archive `FTPStudio-Linux.tar.gz`
- **Windows** : `dist/FTPStudio/` et archive `FTPStudio-Windows.zip`
- **macOS** : `dist/FTPStudio.app` et archive `FTPStudio-macOS.zip`

---

## 🤖 Intégration Continue (GitHub Releases)

Le workflow `.github/workflows/build.yml` compile automatiquement l'application pour Linux, Windows et macOS dès la création d'un tag de version Git :

git tag v1.0.0
git push origin v1.0.0

Les binaires compilés (`.zip` et `.tar.gz`) sont automatiquement publiés et mis à disposition directement dans la section **Releases** de votre dépôt GitHub.

---

## 📁 Structure du Dépôt

ftpstudio/
├── .github/
│   └── workflows/
│       └── build.yml        # CI/CD : Compilation et publication GitHub Releases
├── .gitignore               # Fichiers ignorés par Git
├── build_installer.py       # Script local de packaging PyInstaller
├── main.py                  # Fichier source unique (Moteur réseau, UI, Serveurs)
├── requirements.txt         # Dépendances (CustomTkinter, pyftpdlib, zeroconf, etc.)
└── README.md                # Documentation complète

---

## 📄 Licence

Ce projet est sous licence MIT - libre d'utilisation, de modification et de distribution.
EOF