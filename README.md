# 🌐 FTPStudio

> **Scanneur réseau léger et lanceur d'explorateur natif multi-OS (Linux, Windows, macOS).**

FTPStudio détecte automatiquement les serveurs de fichiers (**FTP, SFTP, FTPS**) ouverts sur votre réseau local et permet de les monter et ouvrir en un clic directement dans le **gestionnaire de fichiers natif de votre système d'exploitation** (Explorateur Windows, Fichiers/Nautilus sous Linux, Finder sous macOS).

---

## ⚡ Pourquoi cette approche ?

Plutôt que de réinventer un explorateur de fichiers tiers au sein de l'application, FTPStudio délègue l'affichage et les transferts à votre OS :
- **0 freeze ni lag** : bénéficiez de toute la fluidité et du cache natif de votre système.
- **Fonctionnalités natives intégrées** : glisser-déposer de fichiers, raccourcis clavier, prévisualisations et menus contextuels du système.
- **Architecture ultra-légère** : le code de l'application tient dans un **seul fichier source autonome** (`main.py`).

---

## 🚀 Fonctionnalités

- 🔍 **Scan réseau multithreadé ultra-rapide** : balayage des ports standards (`21`, `22`, `990`) sur le sous-réseau local en quelques secondes.
- 🟢 **Détection d'accès anonyme** : teste en arrière-plan si le serveur autorise les connexions sans mot de passe.
- 🖥️ **Intégration OS native** :
  - **Linux** : ouvre directement votre explorateur natif (`nautilus`, `dolphin`, `nemo`, `thunar`, `caja`) sans parasitage par le navigateur web.
  - **Windows** : ouvre l'**Explorateur Windows** pour le FTP ou passe le relais à votre client SFTP (WinSCP, FileZilla, etc.).
  - **macOS** : déclenche le dialogue de connexion natif du **Finder**.
- 🔑 **Connexion manuelle** : formulaire rapide pour cibler une IP, un port et des identifiants spécifiques.
- 🎨 **Interface moderne** : propulsée par CustomTkinter avec bascule instantanée entre **thème sombre** 🌙 et **thème clair** ☀️.

---

## 📦 Intégrations par Système d'Exploitation

| Système d'exploitation | Gestionnaire de fichiers ciblé | Protocole FTP | Protocole SFTP |
| :--- | :--- | :---: | :---: |
| **Ubuntu / Debian / Fedora** | **GNOME Fichiers (Nautilus)** | ✅ Natif (GVFS) | ✅ Natif (GVFS) |
| **KDE Plasma** | **Dolphin** | ✅ Natif (KIO) | ✅ Natif (KIO) |
| **Linux Mint / XFCE / MATE** | **Nemo / Thunar / Caja** | ✅ Natif (GVFS) | ✅ Natif (GVFS) |
| **Windows 10 / 11** | **Explorateur Windows** | ✅ Natif | ⚙️ Via client (WinSCP / FileZilla) |
| **macOS** | **Finder** | ✅ Natif | ⚙️ Via gestionnaire URL système |

---

## 🛠️ Installation & Lancement rapide

### Prérequis
- **Python 3.10 ou supérieur**
- Sur Linux (Ubuntu/Debian), assurez-vous d'avoir Tkinter installé :
  `sudo apt-get update && sudo apt-get install -y python3-tk`

### 1. Cloner le dépôt
```bash
git clone https://github.com/votre-utilisateur/ftpstudio.git
cd ftpstudio
```

### 2. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 3. Lancer l'application
```bash
python3 main.py
```

---

## 🔨 Compilation autonome (Binaires exécutables)

Vous pouvez générer un binaire autonome sans dépendance Python pour votre OS à l'aide du script fourni :

```bash
python build_installer.py
```

L'exécutable et son archive prête à distribuer seront générés dans le dossier `dist/` :
- **Linux** : `dist/FTPStudio/` et archive `FTPStudio-Linux.tar.gz`
- **Windows** : `dist/FTPStudio/` et archive `FTPStudio-Windows.zip`
- **macOS** : `dist/FTPStudio.app` et archive `FTPStudio-macOS.zip`

---

## 🤖 Intégration Continue (GitHub Actions)

Le workflow `.github/workflows/build.yml` compile automatiquement l'application pour les 3 systèmes d'exploitation :
- **Compilation manuelle** : déclenchable à tout moment depuis l'onglet **Actions** de GitHub (*Run workflow*), avec téléchargement direct des binaires compilés dans les *Artifacts*.
- **Publication automatique (Releases)** : lors de la création d'un tag de version :
  ```bash
  git tag v1.0.0
  git push origin v1.0.0
  ```

---

## 📁 Structure du Projet

```text
ftpstudio/
├── .github/
│   └── workflows/
│       └── build.yml        # CI/CD : Compilation multi-OS (Linux, Windows, macOS)
├── .gitignore               # Fichiers ignorés par Git
├── build_installer.py       # Script local de packaging PyInstaller
├── main.py                  # Code source unique (Scanner + UI + Moteur OS)
├── requirements.txt         # Dépendances du projet (CustomTkinter, PyInstaller)
└── README.md                # Documentation
```

---

## 📄 Licence

Ce projet est sous licence MIT - vous êtes libre de l'utiliser, le modifier et le distribuer.