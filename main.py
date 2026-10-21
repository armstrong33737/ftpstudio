"""
main.py
=======
FTPStudio - Détection réseau, client OS et serveur FTP embarqué.
Projet autonome en fichier unique multi-OS (Linux, Windows, macOS).
"""

import ipaddress
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from tkinter import filedialog, messagebox
from typing import Callable, List, Optional, Tuple

# Suppression préventive du message parasite appmenu-gtk sous Linux
os.environ["UBUNTU_MENUPROXY"] = "0"
os.environ["NO_AT_BRIDGE"] = "1"

import customtkinter as ctk

# Serveur FTP embarqué
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import ThreadedFTPServer


# ==============================================================================
# 1. MOTEUR DE SCAN DU RÉSEAU LOCAL
# ==============================================================================

@dataclass(frozen=True)
class DetectedServer:
    ip: str
    port: int
    protocol: str       # "FTP", "SFTP" ou "FTPS"
    is_anonymous: bool  # Vrai si connectable sans mot de passe
    banner: str = ""    # Version ou signature hôte


def get_local_ip() -> str:
    """Récupère l'IP locale de la machine hôte."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_network_range(local_ip: str, prefix: int = 24) -> List[str]:
    """Retourne la plage d'adresses IP du sous-réseau local."""
    try:
        net = ipaddress.ip_network(f"{local_ip}/{prefix}", strict=False)
        return [str(ip) for ip in net.hosts()]
    except Exception:
        return [local_ip]


def probe_host_port(ip: str, port: int, timeout: float = 0.35) -> Optional[DetectedServer]:
    """Sonde un port donné pour identifier le service distant."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            if sock.connect_ex((ip, port)) != 0:
                return None

            protocol = "FTP"
            if port in (22, 2222):
                protocol = "SFTP"
            elif port == 990:
                protocol = "FTPS"

            banner = ""
            is_anon = False

            if protocol in ("FTP", "FTPS"):
                import ftplib
                try:
                    f = ftplib.FTP()
                    f.connect(ip, port, timeout=0.6)
                    welcome = f.getwelcome().strip().splitlines()
                    banner = welcome[0][:40] if welcome else "FTP Server"
                    try:
                        f.login("anonymous", "anonymous@")
                        is_anon = True
                    except Exception:
                        is_anon = False
                    f.close()
                except Exception:
                    pass
            elif protocol == "SFTP":
                try:
                    sock.sendall(b"\n")
                    raw = sock.recv(128).decode("utf-8", errors="ignore").strip()
                    if "SSH" in raw:
                        banner = raw[:40]
                except Exception:
                    banner = "OpenSSH"

            return DetectedServer(
                ip=ip, port=port, protocol=protocol, is_anonymous=is_anon, banner=banner
            )
    except Exception:
        return None


def run_network_scan(
    ports: List[int],
    progress_cb: Optional[Callable[[int, int], None]] = None
) -> List[DetectedServer]:
    """Scan multithreadé rapide sur le sous-réseau."""
    local_ip = get_local_ip()
    ip_list = get_network_range(local_ip)
    tasks = [(ip, p) for ip in ip_list for p in ports]
    total = len(tasks)
    done = 0
    results: List[DetectedServer] = []

    with ThreadPoolExecutor(max_workers=140) as executor:
        futures = {executor.submit(probe_host_port, ip, p): (ip, p) for ip, p in tasks}
        for future in as_completed(futures):
            done += 1
            res = future.result()
            if res:
                results.append(res)
            if progress_cb:
                progress_cb(done, total)

    results.sort(key=lambda s: (tuple(int(x) for x in s.ip.split(".")), s.port))
    return results


# ==============================================================================
# 2. OUVERTURE MULTI-OS DANS L'EXPLORATEUR NATIF
# ==============================================================================

def build_remote_url(ip: str, port: int, protocol: str, user: Optional[str] = None, password: Optional[str] = None) -> str:
    """Construit une URL RFC valide avec échappement des caractères spéciaux."""
    scheme = protocol.lower()
    if scheme == "ftps":
        scheme = "ftp"

    auth_part = ""
    if user:
        enc_user = urllib.parse.quote(user, safe="")
        if password:
            enc_pwd = urllib.parse.quote(password, safe="")
            auth_part = f"{enc_user}:{enc_pwd}@"
        else:
            auth_part = f"{enc_user}@"

    is_standard = (scheme == "ftp" and port == 21) or (scheme == "sftp" and port == 22)
    port_part = "" if is_standard else f":{port}"
    return f"{scheme}://{auth_part}{ip}{port_part}/"


def get_linux_file_manager() -> Optional[str]:
    """Détecte le gestionnaire de fichiers natif de la distribution Linux."""
    candidates = [
        "nautilus", "dolphin", "nemo", "thunar", "caja", "pcmanfm-qt", "pcmanfm"
    ]
    for fm in candidates:
        if shutil.which(fm):
            return fm
    return None


def find_windows_sftp_client() -> Optional[str]:
    """Cherche si un client SFTP courant est installé sur Windows."""
    known_paths = [
        shutil.which("winscp.exe"),
        os.path.expandvars(r"%ProgramFiles%\WinSCP\WinSCP.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\WinSCP\WinSCP.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\WinSCP\WinSCP.exe"),
        shutil.which("filezilla.exe"),
        os.path.expandvars(r"%ProgramFiles%\FileZilla FTP Client\filezilla.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\FileZilla FTP Client\filezilla.exe")
    ]
    for path in known_paths:
        if path and os.path.isfile(path):
            return path
    return None


def open_in_native_file_manager(
    ip: str,
    port: int = 21,
    protocol: str = "FTP",
    user: Optional[str] = None,
    password: Optional[str] = None
) -> Tuple[bool, str]:
    """Ouvre l'URL directement dans le gestionnaire de fichiers natif de l'OS."""
    target_url = build_remote_url(ip, port, protocol, user, password)
    system = platform.system()

    try:
        if system == "Windows":
            if protocol.upper() == "SFTP":
                client_path = find_windows_sftp_client()
                if client_path:
                    subprocess.Popen([client_path, target_url])
                    return True, f"SFTP ouvert avec {os.path.basename(client_path)}."
                try:
                    os.startfile(target_url)
                    return True, "Ouverture avec le gestionnaire SFTP associé."
                except OSError:
                    return False, "Windows Explorer ne supporte pas SFTP. Installez WinSCP ou FileZilla."
            else:
                subprocess.Popen(["explorer.exe", target_url])
                return True, "Explorateur Windows ouvert."

        elif system == "Darwin":  # macOS
            res = subprocess.run(["open", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                return True, "Finder ouvert avec 'Se connecter au serveur'."
            else:
                return False, f"Le Finder n'a pas pu monter l'URL ({res.stderr.strip()})."

        else:  # Linux
            fm = get_linux_file_manager()
            if fm:
                subprocess.Popen([fm, target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"Explorateur ouvert ({fm})."

            if shutil.which("gio"):
                subprocess.Popen(["gio", "open", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, "Explorateur ouvert via GIO."
            else:
                subprocess.Popen(["xdg-open", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, "Explorateur ouvert via xdg-open."

    except Exception as exc:
        return False, f"Erreur lors de l'ouverture : {exc}"


# ==============================================================================
# 3. GESTIONNAIRE DU SERVEUR FTP EMBARQUÉ
# ==============================================================================

class EmbeddedFTPServer:
    """Serveur FTP local asynchrone multithreadé."""

    def __init__(self, folder: str, port: int = 2121, user: Optional[str] = None, password: Optional[str] = None, allow_write: bool = True):
        self.folder = folder
        self.port = port
        self.user = user
        self.password = password
        self.allow_write = allow_write
        self.server: Optional[ThreadedFTPServer] = None
        self.is_running = False

    def start(self):
        authorizer = DummyAuthorizer()
        # Droits : "elradfmwMT" (Écriture complète) ou "elr" (Lecture seule)
        perm = "elradfmwMT" if self.allow_write else "elr"

        if self.user and self.password:
            authorizer.add_user(self.user, self.password, self.folder, perm=perm)
        else:
            authorizer.add_anonymous(self.folder, perm=perm)

        handler = FTPHandler
        handler.authorizer = authorizer
        handler.banner = "FTPStudio Embedded Server ready."

        # Écoute sur 0.0.0.0 (toutes les cartes réseau : WiFi, Ethernet, etc.)
        self.server = ThreadedFTPServer(("0.0.0.0", self.port), handler)
        self.server.max_cons = 64
        self.server.max_cons_per_ip = 10

        self.is_running = True
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        try:
            self.server.serve_forever()
        except Exception:
            pass
        finally:
            self.is_running = False

    def stop(self):
        if self.server:
            try:
                self.server.close_all()
            except Exception:
                pass
            self.server = None
        self.is_running = False


# ==============================================================================
# 4. INTERFACE GRAPHIQUE (CUSTOMTKINTER)
# ==============================================================================

class ManualConnectModal(ctk.CTkToplevel):
    """Dialogue de connexion manuelle ou d'authentification."""

    def __init__(self, parent, default_ip="", default_port=21, default_proto="FTP"):
        super().__init__(parent)
        self.title("Connexion au serveur")
        self.geometry("400x370")
        self.resizable(False, False)
        self.grab_set()

        ctk.CTkLabel(
            self, text="Ouvrir dans l'explorateur", font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(16, 12))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(padx=24, fill="x")

        ctk.CTkLabel(form, text="Protocole :").grid(row=0, column=0, sticky="w", pady=4)
        self.proto_menu = ctk.CTkOptionMenu(form, values=["FTP", "SFTP"], width=200)
        self.proto_menu.set(default_proto)
        self.proto_menu.grid(row=0, column=1, pady=4)

        ctk.CTkLabel(form, text="IP / Hôte :").grid(row=1, column=0, sticky="w", pady=4)
        self.ip_entry = ctk.CTkEntry(form, width=200)
        default_base = default_ip or (get_local_ip().rsplit(".", 1)[0] + ".")
        self.ip_entry.insert(0, default_base)
        self.ip_entry.grid(row=1, column=1, pady=4)

        ctk.CTkLabel(form, text="Port :").grid(row=2, column=0, sticky="w", pady=4)
        self.port_entry = ctk.CTkEntry(form, width=200)
        self.port_entry.insert(0, str(default_port))
        self.port_entry.grid(row=2, column=1, pady=4)

        ctk.CTkLabel(form, text="Utilisateur :").grid(row=3, column=0, sticky="w", pady=4)
        self.user_entry = ctk.CTkEntry(form, width=200, placeholder_text="(Vide si anonyme)")
        self.user_entry.grid(row=3, column=1, pady=4)

        ctk.CTkLabel(form, text="Mot de passe :").grid(row=4, column=0, sticky="w", pady=4)
        self.pwd_entry = ctk.CTkEntry(form, width=200, show="*")
        self.pwd_entry.grid(row=4, column=1, pady=4)

        btn_launch = ctk.CTkButton(
            self, text="🚀 Ouvrir dans l'OS", height=36, command=self._on_submit
        )
        btn_launch.pack(pady=20, padx=24, fill="x")

    def _on_submit(self):
        ip = self.ip_entry.get().strip()
        port_raw = self.port_entry.get().strip() or "21"
        port = int(port_raw) if port_raw.isdigit() else 21
        proto = self.proto_menu.get()
        user = self.user_entry.get().strip() or None
        pwd = self.pwd_entry.get().strip() or None

        self.destroy()
        ok, msg = open_in_native_file_manager(ip, port, proto, user, pwd)
        if not ok:
            messagebox.showerror("Erreur d'ouverture", msg)


class FTPStudioApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("FTPStudio - Client & Serveur de Fichiers")
        self.geometry("860x640")
        self.minsize(720, 500)

        self.current_theme = "dark"
        ctk.set_appearance_mode(self.current_theme)
        ctk.set_default_color_theme("blue")

        self.detected_servers: List[DetectedServer] = []
        self._is_scanning = False
        self.embedded_server: Optional[EmbeddedFTPServer] = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. En-tête global
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(14, 2))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_box, text="🌐 FTPStudio", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(side="left")
        ctk.CTkLabel(
            title_box, text="  — Détection Réseau, Client & Mode Serveur",
            font=ctk.CTkFont(size=13), text_color=("gray40", "gray70")
        ).pack(side="left", pady=(6, 0))

        self.theme_btn = ctk.CTkButton(
            header, text="🌙", width=38, height=32, command=self._toggle_theme
        )
        self.theme_btn.grid(row=0, column=1, sticky="e")

        # 2. Onglets : Client (Explorateur) & Serveur (Partage)
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=20, pady=(2, 8))

        self.tab_client = self.tabview.add("🔍 Scanner & Explorateur")
        self.tab_server = self.tabview.add("📁 Mode Serveur (Partager un dossier)")

        self._build_client_tab()
        self._build_server_tab()

        # 3. Pied de page global
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=26, pady=(0, 8))
        footer.grid_columnconfigure(0, weight=1)

        self.status_lbl = ctk.CTkLabel(
            footer, text=f"IP locale : {get_local_ip()} | Prêt.",
            text_color=("gray40", "gray65"), font=ctk.CTkFont(size=12)
        )
        self.status_lbl.grid(row=0, column=0, sticky="w")

    # ==========================================================================
    # ONGLET 1 : CLIENT & SCANNER
    # ==========================================================================
    def _build_client_tab(self):
        tab = self.tab_client
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Panneau de contrôle
        control_card = ctk.CTkFrame(tab, corner_radius=10)
        control_card.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 8))
        control_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(control_card, text="Ports :", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=(14, 6), pady=12, sticky="w"
        )
        self.ports_entry = ctk.CTkEntry(control_card, width=170, height=30)
        # Inclusion de 2121 pour trouver immédiatement d'autres instances de FTPStudio
        self.ports_entry.insert(0, "21, 22, 990, 2121")
        self.ports_entry.grid(row=0, column=1, sticky="w", pady=12)

        btn_box = ctk.CTkFrame(control_card, fg_color="transparent")
        btn_box.grid(row=0, column=2, padx=12, pady=12, sticky="e")

        self.scan_btn = ctk.CTkButton(
            btn_box, text="🔍 Scanner le réseau", height=32, command=self._start_scan
        )
        self.scan_btn.pack(side="left", padx=4)

        btn_manual = ctk.CTkButton(
            btn_box, text="➕ Manuel...", height=32, width=110,
            fg_color=("gray75", "gray25"), text_color=("black", "white"),
            command=lambda: ManualConnectModal(self)
        )
        btn_manual.pack(side="left", padx=4)

        self.progress_bar = ctk.CTkProgressBar(tab, height=4)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=0, sticky="sew", padx=14, pady=0)

        # Liste scrollable des serveurs détectés
        self.servers_scroll = ctk.CTkScrollableFrame(tab, label_text="Serveurs détectés sur le réseau")
        self.servers_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 6))

        self._render_empty_state("Cliquez sur 'Scanner le réseau' pour détecter les serveurs.")

    def _render_empty_state(self, message: str):
        for w in self.servers_scroll.winfo_children():
            w.destroy()
        box = ctk.CTkFrame(self.servers_scroll, fg_color="transparent")
        box.pack(expand=True, fill="both", pady=70)
        ctk.CTkLabel(box, text="📡", font=ctk.CTkFont(size=44)).pack(pady=(0, 8))
        ctk.CTkLabel(
            box, text=message, font=ctk.CTkFont(size=13), text_color=("gray40", "gray65")
        ).pack()

    def _start_scan(self):
        if self._is_scanning:
            return

        ports_raw = self.ports_entry.get().split(",")
        ports = []
        for p in ports_raw:
            p = p.strip()
            if p.isdigit() and 1 <= int(p) <= 65535:
                ports.append(int(p))
        if not ports:
            ports = [21, 22, 990, 2121]

        self._is_scanning = True
        self.scan_btn.configure(state="disabled", text="Scan en cours...")
        self.progress_bar.set(0)
        self.status_lbl.configure(text="Recherche des serveurs ouverts sur le réseau...")

        for w in self.servers_scroll.winfo_children():
            w.destroy()

        def worker():
            def on_progress(done, total):
                self.after(0, lambda: self.progress_bar.set(done / total if total else 0))

            results = run_network_scan(ports=ports, progress_cb=on_progress)
            self.after(0, lambda: self._on_scan_completed(results))

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_completed(self, results: List[DetectedServer]):
        self._is_scanning = False
        self.scan_btn.configure(state="normal", text="🔍 Scanner le réseau")
        self.progress_bar.set(1.0)
        self.detected_servers = results

        for w in self.servers_scroll.winfo_children():
            w.destroy()

        if not results:
            self.status_lbl.configure(text="Scan terminé. Aucun serveur détecté.")
            self._render_empty_state("Aucun serveur FTP ou SFTP ouvert trouvé.")
            return

        self.status_lbl.configure(text=f"Scan terminé : {len(results)} serveur(s) trouvé(s).")

        for s in results:
            card = ctk.CTkFrame(self.servers_scroll, corner_radius=8)
            card.pack(fill="x", pady=4, padx=4)
            card.grid_columnconfigure(1, weight=1)

            badge = "🟢" if s.is_anonymous else ("🛡️" if s.protocol == "SFTP" else "🔒")
            lbl_icon = ctk.CTkLabel(card, text=badge, font=ctk.CTkFont(size=20), width=32)
            lbl_icon.grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=8)

            lbl_title = ctk.CTkLabel(
                card, text=f"{s.protocol} — {s.ip}:{s.port}",
                font=ctk.CTkFont(size=14, weight="bold"), anchor="w"
            )
            lbl_title.grid(row=0, column=1, sticky="w", padx=4, pady=(6, 0))

            auth_desc = "Accès anonyme libre" if s.is_anonymous else "Authentification requise"
            lbl_sub = ctk.CTkLabel(
                card, text=f"{auth_desc} • {s.banner or 'Prêt'}",
                font=ctk.CTkFont(size=11), text_color=("gray45", "gray70"), anchor="w"
            )
            lbl_sub.grid(row=1, column=1, sticky="w", padx=4, pady=(0, 6))

            btn_actions = ctk.CTkFrame(card, fg_color="transparent")
            btn_actions.grid(row=0, column=2, rowspan=2, padx=10, pady=8, sticky="e")

            if not s.is_anonymous:
                btn_auth = ctk.CTkButton(
                    btn_actions, text="🔑 S'authentifier...", width=120, height=28,
                    fg_color=("gray75", "gray25"), text_color=("black", "white"),
                    command=lambda srv=s: ManualConnectModal(
                        self, default_ip=srv.ip, default_port=srv.port, default_proto=srv.protocol
                    )
                )
                btn_auth.pack(side="left", padx=4)

            btn_open = ctk.CTkButton(
                btn_actions, text="🚀 Ouvrir dans l'OS", width=130, height=28,
                command=lambda srv=s: self._open_server(srv)
            )
            btn_open.pack(side="left", padx=4)

    def _open_server(self, server: DetectedServer):
        if not server.is_anonymous:
            ManualConnectModal(
                self, default_ip=server.ip, default_port=server.port, default_proto=server.protocol
            )
        else:
            ok, msg = open_in_native_file_manager(ip=server.ip, port=server.port, protocol=server.protocol)
            if not ok:
                messagebox.showerror("Erreur", msg)
            else:
                self.status_lbl.configure(text=f"Explorateur ouvert pour {server.ip}:{server.port}")

    # ==========================================================================
    # ONGLET 2 : MODE SERVEUR EMBARQUÉ (PARTAGE)
    # ==========================================================================
    def _build_server_tab(self):
        tab = self.tab_server
        tab.grid_columnconfigure(0, weight=1)

        # 1. Sélection du dossier
        dir_card = ctk.CTkFrame(tab, corner_radius=10)
        dir_card.pack(fill="x", padx=14, pady=(12, 8))
        dir_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(dir_card, text="Dossier partagé :", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=14, pady=12, sticky="w"
        )

        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.exists(default_dir):
            default_dir = os.path.expanduser("~")

        self.server_dir_entry = ctk.CTkEntry(dir_card)
        self.server_dir_entry.insert(0, default_dir)
        self.server_dir_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=12)

        btn_browse = ctk.CTkButton(
            dir_card, text="📁 Parcourir...", width=100, command=self._choose_server_dir
        )
        btn_browse.grid(row=0, column=2, padx=(4, 14), pady=12)

        # 2. Options de configuration
        opts_card = ctk.CTkFrame(tab, corner_radius=10)
        opts_card.pack(fill="x", padx=14, pady=8)
        opts_card.grid_columnconfigure(1, weight=1)

        # Port
        ctk.CTkLabel(opts_card, text="Port d'écoute :", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=14, pady=8, sticky="w"
        )
        self.server_port_entry = ctk.CTkEntry(opts_card, width=120)
        self.server_port_entry.insert(0, "2121")
        self.server_port_entry.grid(row=0, column=1, sticky="w", padx=8, pady=8)

        # Permissions d'écriture
        self.write_perm_var = ctk.BooleanVar(value=True)
        chk_write = ctk.CTkCheckBox(
            opts_card, text="Autoriser l'écriture (Téléversement / Suppression par les clients)",
            variable=self.write_perm_var
        )
        chk_write.grid(row=1, column=0, columnspan=2, padx=14, pady=8, sticky="w")

        # Authentification
        self.auth_mode_var = ctk.StringVar(value="anon")
        auth_box = ctk.CTkFrame(opts_card, fg_color="transparent")
        auth_box.grid(row=2, column=0, columnspan=2, padx=14, pady=8, sticky="w")

        ctk.CTkRadioButton(
            auth_box, text="Accès anonyme (Tous les appareils du réseau)",
            variable=self.auth_mode_var, value="anon", command=self._toggle_auth_fields
        ).pack(side="left", padx=(0, 20))

        ctk.CTkRadioButton(
            auth_box, text="Protection par mot de passe",
            variable=self.auth_mode_var, value="auth", command=self._toggle_auth_fields
        ).pack(side="left")

        # Champs Utilisateur / Mot de passe (cachés par défaut)
        self.auth_fields_frame = ctk.CTkFrame(opts_card, fg_color="transparent")
        self.auth_fields_frame.grid(row=3, column=0, columnspan=2, padx=14, pady=(0, 10), sticky="ew")

        ctk.CTkLabel(self.auth_fields_frame, text="Utilisateur :").pack(side="left", padx=(0, 6))
        self.srv_user_entry = ctk.CTkEntry(self.auth_fields_frame, width=130)
        self.srv_user_entry.insert(0, "user")
        self.srv_user_entry.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(self.auth_fields_frame, text="Mot de passe :").pack(side="left", padx=(0, 6))
        self.srv_pwd_entry = ctk.CTkEntry(self.auth_fields_frame, width=130, show="*")
        self.srv_pwd_entry.insert(0, "1234")
        self.srv_pwd_entry.pack(side="left")

        self._toggle_auth_fields()

        # 3. Bouton principal Démarrer / Arrêter
        self.btn_toggle_server = ctk.CTkButton(
            tab, text="▶ Démarrer le serveur", font=ctk.CTkFont(size=15, weight="bold"),
            height=40, fg_color="#16a34a", hover_color="#15803d", command=self._toggle_server
        )
        self.btn_toggle_server.pack(fill="x", padx=14, pady=(10, 8))

        # 4. Carte d'état en direct
        self.server_status_card = ctk.CTkFrame(tab, corner_radius=10)
        self.server_status_card.pack(fill="x", padx=14, pady=8)

        self.lbl_server_state = ctk.CTkLabel(
            self.server_status_card, text="🔴 Serveur arrêté",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=("gray40", "gray65")
        )
        self.lbl_server_state.pack(pady=(12, 4))

        self.lbl_server_url = ctk.CTkLabel(
            self.server_status_card, text="--",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.lbl_server_url.pack(pady=4)

        self.server_actions_box = ctk.CTkFrame(self.server_status_card, fg_color="transparent")
        self.server_actions_box.pack(pady=(4, 12))

        self.btn_copy_url = ctk.CTkButton(
            self.server_actions_box, text="📋 Copier le lien", width=120, height=28,
            command=self._copy_server_url, state="disabled"
        )
        self.btn_copy_url.pack(side="left", padx=6)

        self.btn_test_local = ctk.CTkButton(
            self.server_actions_box, text="🚀 Ouvrir dans mon OS", width=160, height=28,
            command=self._open_local_server_in_os, state="disabled"
        )
        self.btn_test_local.pack(side="left", padx=6)

    def _choose_server_dir(self):
        ch = filedialog.askdirectory(initialdir=self.server_dir_entry.get())
        if ch:
            self.server_dir_entry.delete(0, "end")
            self.server_dir_entry.insert(0, ch)

    def _toggle_auth_fields(self):
        if self.auth_mode_var.get() == "auth":
            self.auth_fields_frame.grid()
        else:
            self.auth_fields_frame.grid_remove()

    def _toggle_server(self):
        if self.embedded_server and self.embedded_server.is_running:
            # Arrêt du serveur
            self.embedded_server.stop()
            self.embedded_server = None

            self.btn_toggle_server.configure(
                text="▶ Démarrer le serveur", fg_color="#16a34a", hover_color="#15803d"
            )
            self.lbl_server_state.configure(text="🔴 Serveur arrêté", text_color=("gray40", "gray65"))
            self.lbl_server_url.configure(text="--")
            self.btn_copy_url.configure(state="disabled")
            self.btn_test_local.configure(state="disabled")
            self.status_lbl.configure(text="Serveur FTP local arrêté.")
        else:
            # Démarrage du serveur
            folder = self.server_dir_entry.get().strip()
            if not os.path.exists(folder):
                messagebox.showerror("Erreur", "Le dossier spécifié n'existe pas.")
                return

            port_raw = self.server_port_entry.get().strip()
            port = int(port_raw) if port_raw.isdigit() else 2121

            user = None
            pwd = None
            if self.auth_mode_var.get() == "auth":
                user = self.srv_user_entry.get().strip() or "user"
                pwd = self.srv_pwd_entry.get().strip() or "1234"

            allow_w = self.write_perm_var.get()

            try:
                self.embedded_server = EmbeddedFTPServer(
                    folder=folder, port=port, user=user, password=pwd, allow_write=allow_w
                )
                self.embedded_server.start()

                local_ip = get_local_ip()
                url = f"ftp://{local_ip}:{port}"

                self.btn_toggle_server.configure(
                    text="⏹ Arrêter le serveur", fg_color="#dc2626", hover_color="#b91c1c"
                )
                self.lbl_server_state.configure(
                    text="🟢 Serveur actif et accessible sur le réseau !", text_color="#16a34a"
                )
                self.lbl_server_url.configure(text=url)
                self.btn_copy_url.configure(state="normal")
                self.btn_test_local.configure(state="normal")
                self.status_lbl.configure(text=f"Serveur FTP actif sur {url} (Dossier : {folder})")

            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de démarrer le serveur :\n{e}")

    def _copy_server_url(self):
        url = self.lbl_server_url.cget("text")
        if url and url != "--":
            self.clipboard_clear()
            self.clipboard_append(url)
            messagebox.showinfo("Copié", f"Lien copié dans le presse-papier :\n{url}")

    def _open_local_server_in_os(self):
        if not self.embedded_server or not self.embedded_server.is_running:
            return
        local_ip = get_local_ip()
        port = self.embedded_server.port
        user = self.embedded_server.user
        pwd = self.embedded_server.password
        open_in_native_file_manager(ip=local_ip, port=port, protocol="FTP", user=user, password=pwd)

    def _toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        ctk.set_appearance_mode(self.current_theme)
        self.theme_btn.configure(text="☀️" if self.current_theme == "light" else "🌙")

    def _on_app_close(self):
        if self.embedded_server and self.embedded_server.is_running:
            self.embedded_server.stop()
        self.destroy()


if __name__ == "__main__":
    app = FTPStudioApp()
    app.mainloop()