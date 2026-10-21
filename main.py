"""
main.py
=======
FTPStudio - Découverte réseau à large spectre et Partage par nom d'hôte.
Version autonome en fichier unique multi-OS (Linux, Windows, macOS).
"""

import html as html_lib
import http.server
import io
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from tkinter import filedialog, messagebox
from typing import Callable, Dict, List, Optional, Tuple

# Suppression préventive des messages parasites GTK sous Linux
os.environ["UBUNTU_MENUPROXY"] = "0"
os.environ["NO_AT_BRIDGE"] = "1"

import customtkinter as ctk
from PIL import Image, ImageDraw

# Modules avec tolérance de panne
try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

try:
    from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False

try:
    import pystray
    HAS_SYSTRAY = True
except ImportError:
    HAS_SYSTRAY = False

# Moteur FTP
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import ThreadedFTPServer

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ftpstudio")
FAVORITES_FILE = os.path.join(CONFIG_DIR, "favorites.json")


# ==============================================================================
# 1. UTILITAIRES & SCAN À LARGE SPECTRE
# ==============================================================================

@dataclass(frozen=True)
class DetectedServer:
    ip: str
    port: int
    protocol: str       # "FTP", "SFTP", "HTTP"
    is_anonymous: bool
    server_name: str = ""
    banner: str = ""
    is_mdns: bool = False


def format_file_size(size_bytes: int) -> str:
    s = float(size_bytes)
    for u in ("o", "Ko", "Mo", "Go"):
        if s < 1024:
            return f"{s:.0f} {u}" if u == "o" else f"{s:.1f} {u}"
        s /= 1024
    return f"{s:.1f} To"


def get_primary_ip() -> str:
    """Détecte l'adresse IP active (Wi-Fi ou câble)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def get_expanded_scan_ports() -> List[int]:
    """Génère la large plage de ports demandée."""
    ports = set()
    ports.update(range(20, 31))       # 20 à 30 (FTP data/cmd, SSH 22, Telnet 23...)
    ports.add(80)                     # HTTP standard
    ports.add(990)                    # FTPS sécurisé
    ports.update(range(2121, 2131))   # 2121 à 2130 (FTPStudio & FTP alternatifs)
    ports.update(range(2221, 2231))   # 2221 à 2230 (SFTP alternatifs)
    ports.update(range(8000, 8011))   # 8000 à 8010 (Web alternatifs)
    ports.update(range(8080, 8096))   # 8080 à 8095 (Web alternatifs étendus)
    return sorted(list(ports))


def probe_host_port(ip: str, port: int, timeout: float = 0.22) -> Optional[DetectedServer]:
    """Sonde un port donné et extrait le nom d'hôte si disponible."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            if sock.connect_ex((ip, port)) != 0:
                return None

            protocol = "FTP"
            if port in [22] or (2221 <= port <= 2230):
                protocol = "SFTP"
            elif port in [80] or (8000 <= port <= 8010) or (8080 <= port <= 8095):
                protocol = "HTTP"

            server_name = ""
            banner = ""
            is_anon = False

            if protocol == "FTP":
                import ftplib
                try:
                    f = ftplib.FTP()
                    f.connect(ip, port, timeout=0.5)
                    welcome = f.getwelcome().strip().splitlines()
                    if welcome:
                        raw = welcome[0][:60]
                        banner = raw
                        if "FTPStudio[" in raw:
                            server_name = raw.split("FTPStudio[", 1)[1].split("]", 1)[0]
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
                    banner = "SSH / SFTP"

            elif protocol == "HTTP":
                banner = "Serveur Web"
                try:
                    sock.sendall(f"HEAD / HTTP/1.1\r\nHost: {ip}\r\nConnection: close\r\n\r\n".encode())
                    resp = sock.recv(512).decode("utf-8", errors="ignore")
                    for line in resp.splitlines():
                        if line.lower().startswith("x-server-name:"):
                            server_name = line.split(":", 1)[1].strip()
                            break
                except Exception:
                    pass

            return DetectedServer(
                ip=ip, port=port, protocol=protocol, is_anonymous=is_anon,
                server_name=server_name, banner=banner
            )
    except Exception:
        return None


def run_expanded_scan(progress_cb=None) -> List[DetectedServer]:
    """Balaye le sous-réseau avec un pool élargi de 250 threads."""
    primary_ip = get_primary_ip()
    base_subnet = primary_ip.rsplit(".", 1)[0] + ".0/24"
    ports = get_expanded_scan_ports()

    try:
        net = ipaddress.ip_network(base_subnet, strict=False)
        ip_list = [str(ip) for ip in net.hosts()]
    except Exception:
        ip_list = [primary_ip]

    tasks = [(ip, p) for ip in ip_list for p in ports]
    total = len(tasks)
    done = 0
    results: List[DetectedServer] = []

    with ThreadPoolExecutor(max_workers=250) as executor:
        futures = {executor.submit(probe_host_port, ip, p): (ip, p) for ip, p in tasks}
        for future in as_completed(futures):
            done += 1
            res = future.result()
            if res:
                results.append(res)
            if progress_cb and done % 15 == 0:
                progress_cb(done, total)

    if progress_cb:
        progress_cb(total, total)

    results.sort(key=lambda s: (tuple(int(x) for x in s.ip.split(".")), s.port))
    return results


# ==============================================================================
# 2. DÉCOUVERTE MDNS / ZEROCONF
# ==============================================================================

class MDNSDiscoveryManager:
    def __init__(self, on_server_found: Callable[[DetectedServer], None]):
        self.on_server_found = on_server_found
        self.zeroconf: Optional[Zeroconf] = None
        self.browser: Optional[ServiceBrowser] = None
        self.registered_info: Optional[ServiceInfo] = None

    def start_discovery(self):
        if not HAS_ZEROCONF:
            return
        try:
            self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self.browser = ServiceBrowser(self.zeroconf, "_ftpstudio._tcp.local.", handlers=[self._on_service_state_change])
        except Exception:
            pass

    def _on_service_state_change(self, zeroconf, service_type, name, state_change):
        from zeroconf import ServiceStateChange
        if state_change is ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info and info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                port = info.port
                props = {k.decode(): v.decode() for k, v in info.properties.items()}
                proto = props.get("proto", "FTP")
                anon = props.get("anon", "True") == "True"
                srv_name = props.get("name", name.split(".")[0])
                srv = DetectedServer(
                    ip=ip, port=port, protocol=proto, is_anonymous=anon,
                    server_name=srv_name, banner="Partage FTPStudio", is_mdns=True
                )
                self.on_server_found(srv)

    def register_server(self, ip: str, port: int, protocol: str = "FTP", server_name: str = "", is_anonymous: bool = True):
        if not HAS_ZEROCONF or not self.zeroconf:
            return
        try:
            self.unregister_server()
            clean_name = "".join(c for c in server_name if c.isalnum() or c in ("-", "_")).strip() or "Partage"
            desc = {"proto": protocol, "anon": str(is_anonymous), "name": server_name}
            service_fullname = f"{clean_name}-{port}._ftpstudio._tcp.local."
            self.registered_info = ServiceInfo(
                "_ftpstudio._tcp.local.",
                service_fullname,
                addresses=[socket.inet_aton(ip)],
                port=port,
                properties=desc,
                server=f"{clean_name}.local."
            )
            self.zeroconf.register_service(self.registered_info)
        except Exception:
            pass

    def unregister_server(self):
        if self.zeroconf and self.registered_info:
            try:
                self.zeroconf.unregister_service(self.registered_info)
            except Exception:
                pass
            self.registered_info = None

    def close(self):
        self.unregister_server()
        if self.zeroconf:
            try:
                self.zeroconf.close()
            except Exception:
                pass


# ==============================================================================
# 3. LANCEUR D'EXPLORATEUR OS NATIF
# ==============================================================================

def get_linux_file_manager() -> Optional[str]:
    for fm in ["nautilus", "dolphin", "nemo", "thunar", "caja", "pcmanfm-qt", "pcmanfm"]:
        if shutil.which(fm):
            return fm
    return None


def open_in_native_file_manager(
    ip: str, port: int = 21, protocol: str = "FTP", user: Optional[str] = None, password: Optional[str] = None
) -> Tuple[bool, str]:
    proto_scheme = protocol.lower()

    if proto_scheme == "http":
        webbrowser.open(f"http://{ip}:{port}/")
        return True, "Navigateur Web ouvert."

    auth = ""
    if user:
        u_enc = urllib.parse.quote(user, safe="")
        p_enc = f":{urllib.parse.quote(password, safe='')}" if password else ""
        auth = f"{u_enc}{p_enc}@"

    is_std = (proto_scheme == "ftp" and port == 21) or (proto_scheme == "sftp" and port == 22)
    port_part = "" if is_std else f":{port}"
    target_url = f"{proto_scheme}://{auth}{ip}{port_part}/"

    system = platform.system()
    try:
        if system == "Windows":
            if proto_scheme == "sftp":
                try:
                    os.startfile(target_url)
                    return True, "SFTP ouvert."
                except OSError:
                    return False, "Pour SFTP sous Windows, installez WinSCP."
            else:
                subprocess.Popen(["explorer.exe", target_url])
                return True, "Explorateur Windows ouvert."

        elif system == "Darwin":
            subprocess.Popen(["open", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return True, "Finder ouvert."

        else:  # Linux (Nautilus, Dolphin, Thunar...)
            fm = get_linux_file_manager()
            if fm:
                subprocess.Popen([fm, target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"Explorateur ouvert ({fm})."
            if shutil.which("gio"):
                subprocess.Popen(["gio", "open", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, "Ouvert via GIO."
            subprocess.Popen(["xdg-open", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "Ouvert."

    except Exception as e:
        return False, f"Impossible d'ouvrir l'explorateur : {e}"


# ==============================================================================
# 4. GESTION DES FAVORIS (JSON)
# ==============================================================================

class FavoritesManager:
    @staticmethod
    def load() -> List[Dict]:
        if not os.path.exists(FAVORITES_FILE):
            return []
        try:
            with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    @staticmethod
    def save(favs: List[Dict]):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
                json.dump(favs, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    @classmethod
    def toggle(cls, server: DetectedServer) -> bool:
        favs = cls.load()
        existing = next((i for i, f in enumerate(favs) if f["ip"] == server.ip and f["port"] == server.port), None)
        if existing is not None:
            favs.pop(existing)
            cls.save(favs)
            return False
        else:
            favs.append({
                "ip": server.ip, "port": server.port, "protocol": server.protocol,
                "server_name": server.server_name, "banner": server.banner,
                "is_anonymous": server.is_anonymous
            })
            cls.save(favs)
            return True

    @classmethod
    def is_favorite(cls, server: DetectedServer) -> bool:
        return any(f["ip"] == server.ip and f["port"] == server.port for f in cls.load())


# ==============================================================================
# 5. MOTEURS SERVEURS (FTP & WEB EXPLORER)
# ==============================================================================

class ProFTPHandler(FTPHandler):
    passive_ports = range(60000, 60050)


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    current_server_name = "FTPStudio"

    def log_message(self, format, *args):
        pass

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.endswith('/'):
                self.send_response(301)
                new_parts = (parts[0], parts[1], parts[2] + '/', parts[3], parts[4])
                self.send_header("Location", urllib.parse.urlunsplit(new_parts))
                self.end_headers()
                return None
            return self.render_web_explorer(path)
        return super().send_head()

    def render_web_explorer(self, path):
        try:
            entries = os.listdir(path)
        except OSError:
            self.send_error(404, "Impossible d'accéder au dossier")
            return None

        entries.sort(key=lambda a: (not os.path.isdir(os.path.join(path, a)), a.lower()))
        displaypath = urllib.parse.unquote(self.path)
        title_name = html_lib.escape(self.current_server_name)

        html_code = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title_name} - {html_lib.escape(displaypath)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 16px; }}
        .container {{ max-width: 860px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 20px; box-shadow: 0 10px 25px rgba(0,0,0,0.4); }}
        h1 {{ font-size: 20px; margin: 0 0 12px 0; color: #38bdf8; display: flex; align-items: center; gap: 8px; }}
        .path {{ background: #0f172a; padding: 10px 14px; border-radius: 6px; font-family: monospace; font-size: 13px; margin-bottom: 16px; word-break: break-all; color: #94a3b8; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px 10px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
        tr:hover {{ background: #2d3b4e; }}
        a {{ color: #f8fafc; text-decoration: none; display: flex; align-items: center; gap: 8px; font-weight: 500; font-size: 14px; }}
        a:hover {{ color: #38bdf8; }}
        .icon {{ font-size: 20px; }}
        .size {{ color: #94a3b8; font-size: 13px; font-family: monospace; }}
        .btn {{ display: inline-block; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: bold; text-decoration: none; }}
        .btn-dl {{ background: #2563eb; color: #ffffff; }}
        .btn-open {{ background: #475569; color: #ffffff; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🌐 {title_name}</h1>
        <div class="path">📁 Emplacement : {html_lib.escape(displaypath)}</div>
        <table>
            <thead>
                <tr>
                    <th>Nom du fichier</th>
                    <th style="width: 120px;">Taille</th>
                    <th style="width: 120px; text-align: right;">Action</th>
                </tr>
            </thead>
            <tbody>
"""
        if displaypath != '/':
            parent = urllib.parse.urljoin(self.path, "..")
            html_code += f"""
                <tr>
                    <td><a href="{parent}"><span class="icon">🔙</span> .. (Dossier parent)</a></td>
                    <td class="size">--</td>
                    <td style="text-align: right;"><a href="{parent}" class="btn btn-open">Ouvrir</a></td>
                </tr>
            """

        for name in entries:
            fullname = os.path.join(path, name)
            is_dir = os.path.isdir(fullname)
            linkname = urllib.parse.quote(name) + ("/" if is_dir else "")
            icon = "📁" if is_dir else "📄"

            if is_dir:
                size_str = "Dossier"
                action = f'<a href="{linkname}" class="btn btn-open">Ouvrir</a>'
            else:
                try:
                    size_str = format_file_size(os.path.getsize(fullname))
                except OSError:
                    size_str = "--"
                action = f'<a href="{linkname}" download class="btn btn-dl">⬇ Télécharger</a>'

            html_code += f"""
                <tr>
                    <td><a href="{linkname}"><span class="icon">{icon}</span> {html_lib.escape(name)}</a></td>
                    <td class="size">{size_str}</td>
                    <td style="text-align: right;">{action}</td>
                </tr>
            """

        html_code += "</tbody></table></div></body></html>"
        encoded = html_code.encode("utf-8", "surrogateescape")
        f = io.BytesIO()
        f.write(encoded)
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("X-Server-Name", self.current_server_name)
        self.end_headers()
        return f


class EmbeddedServerController:
    def __init__(self):
        self.is_running = False
        self.mode = "FTP"
        self.server_name = socket.gethostname()
        self.folder = ""
        self.port = 2121
        self.display_ip = get_primary_ip()
        self.user = None
        self.password = None
        self.allow_write = True

        self.ftp_server = None
        self.http_server = None

    def start(self, mode: str, server_name: str, folder: str, port: int, user=None, pwd=None, allow_write=True):
        self.mode = mode
        self.server_name = server_name.strip() or socket.gethostname()
        self.folder = folder
        self.port = port
        self.display_ip = get_primary_ip()
        self.user = user
        self.password = pwd
        self.allow_write = allow_write

        if self.mode == "FTP":
            authorizer = DummyAuthorizer()
            perm = "elradfmwMT" if self.allow_write else "elr"
            if self.user and self.password:
                authorizer.add_user(self.user, self.password, self.folder, perm=perm)
            else:
                authorizer.add_anonymous(self.folder, perm=perm)

            ProFTPHandler.authorizer = authorizer
            ProFTPHandler.banner = f"FTPStudio[{self.server_name}] Ready."

            self.ftp_server = ThreadedFTPServer(("0.0.0.0", self.port), ProFTPHandler)
            self.ftp_server.max_cons = 64
            self.ftp_server.max_cons_per_ip = 10
            threading.Thread(target=self._run_ftp, daemon=True).start()
        else:
            CustomHTTPRequestHandler.current_server_name = self.server_name
            handler = lambda *args, **kwargs: CustomHTTPRequestHandler(*args, directory=self.folder, **kwargs)
            self.http_server = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), handler)
            threading.Thread(target=self._run_http, daemon=True).start()

        self.is_running = True

    def _run_ftp(self):
        try:
            self.ftp_server.serve_forever()
        except Exception:
            pass
        finally:
            self.is_running = False

    def _run_http(self):
        try:
            self.http_server.serve_forever()
        except Exception:
            pass
        finally:
            self.is_running = False

    def stop(self):
        if self.ftp_server:
            try:
                self.ftp_server.close_all()
            except Exception:
                pass
            self.ftp_server = None

        if self.http_server:
            try:
                self.http_server.shutdown()
                self.http_server.server_close()
            except Exception:
                pass
            self.http_server = None

        self.is_running = False

    def get_url(self) -> str:
        proto = "http" if self.mode == "HTTP" else "ftp"
        return f"{proto}://{self.display_ip}:{self.port}"


# ==============================================================================
# 6. INTERFACE GRAPHIQUE ÉPURÉE (CUSTOMTKINTER)
# ==============================================================================

class AdvancedOptionsModal(ctk.CTkToplevel):
    def __init__(self, parent, on_connect_manual: Callable):
        super().__init__(parent)
        self.title("Options Avancées & Connexion Manuelle")
        self.geometry("380x320")
        self.resizable(False, False)
        self.grab_set()

        ctk.CTkLabel(self, text="Connexion manuelle directe", font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 10))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(padx=24, fill="x")

        ctk.CTkLabel(form, text="Protocole :").grid(row=0, column=0, sticky="w", pady=4)
        self.proto_menu = ctk.CTkOptionMenu(form, values=["FTP", "SFTP", "HTTP"], width=180)
        self.proto_menu.grid(row=0, column=1, pady=4)

        ctk.CTkLabel(form, text="Adresse IP :").grid(row=1, column=0, sticky="w", pady=4)
        self.ip_entry = ctk.CTkEntry(form, width=180)
        self.ip_entry.insert(0, get_primary_ip().rsplit(".", 1)[0] + ".")
        self.ip_entry.grid(row=1, column=1, pady=4)

        ctk.CTkLabel(form, text="Port :").grid(row=2, column=0, sticky="w", pady=4)
        self.port_entry = ctk.CTkEntry(form, width=180)
        self.port_entry.insert(0, "21")
        self.port_entry.grid(row=2, column=1, pady=4)

        ctk.CTkLabel(form, text="Identifiant :").grid(row=3, column=0, sticky="w", pady=4)
        self.user_entry = ctk.CTkEntry(form, width=180, placeholder_text="(Vide si libre)")
        self.user_entry.grid(row=3, column=1, pady=4)

        ctk.CTkLabel(form, text="Mot de passe :").grid(row=4, column=0, sticky="w", pady=4)
        self.pwd_entry = ctk.CTkEntry(form, width=180, show="*")
        self.pwd_entry.grid(row=4, column=1, pady=4)

        def _do_connect():
            ip = self.ip_entry.get().strip()
            port = int(self.port_entry.get().strip() or "21")
            proto = self.proto_menu.get()
            user = self.user_entry.get().strip() or None
            pwd = self.pwd_entry.get().strip() or None
            self.destroy()
            on_connect_manual(ip, port, proto, user, pwd)

        ctk.CTkButton(self, text="🚀 Se connecter", height=34, command=_do_connect).pack(pady=16, padx=24, fill="x")


class FTPStudioApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("FTPStudio - Découverte & Partage Réseau")
        self.geometry("880x660")
        self.minsize(760, 540)

        self.current_theme = "dark"
        ctk.set_appearance_mode(self.current_theme)
        ctk.set_default_color_theme("blue")

        self.detected_servers: List[DetectedServer] = []
        self._is_scanning = False

        self.server_ctrl = EmbeddedServerController()
        self.mdns_manager = MDNSDiscoveryManager(on_server_found=self._on_mdns_found)
        self.tray_icon = None

        # Liaison des raccourcis universels pour fermer l'appli (Ctrl+Q ou Cmd+Q)
        self.bind("<Control-q>", lambda e: self._quit_app())
        self.bind("<Command-q>", lambda e: self._quit_app())

        self._build_ui()
        self._init_systray()
        self.mdns_manager.start_discovery()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # En-tête
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(14, 4))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(title_box, text="🌐 FTPStudio", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(title_box, text="  — Partagez et ouvrez des dossiers en un clic", font=ctk.CTkFont(size=13), text_color=("gray40", "gray70")).pack(side="left", pady=(5, 0))

        # Conteneur des boutons d'actions d'en-tête (Thème + Bouton Quitter direct)
        btn_box = ctk.CTkFrame(header, fg_color="transparent")
        btn_box.grid(row=0, column=1, sticky="e")

        self.theme_btn = ctk.CTkButton(btn_box, text="🌙", width=36, height=32, command=self._toggle_theme)
        self.theme_btn.pack(side="left", padx=(0, 6))

        # self.btn_quit = ctk.CTkButton(
        #     btn_box, text="✕", width=36, height=32,
        #     fg_color=("#ef4444", "#dc2626"), hover_color="#b91c1c",
        #     command=self._quit_app
        # )
        # self.btn_quit.pack(side="left")

        # Deux onglets clairs
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 6))

        self.tab_client = self.tabview.add("🔍 Appareils du Réseau")
        self.tab_server = self.tabview.add("📁 Partager un Dossier")

        self._build_client_tab()
        self._build_server_tab()

        # Pied de page
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 8))
        footer.grid_columnconfigure(0, weight=1)

        self.status_lbl = ctk.CTkLabel(
            footer, text=f"Connecté ({get_primary_ip()}) — Ordinateur : {socket.gethostname()}",
            text_color=("gray40", "gray65"), font=ctk.CTkFont(size=12)
        )
        self.status_lbl.grid(row=0, column=0, sticky="w")

    # ==========================================================================
    # ONGLET 1 : DÉCOUVERTE SIMPLE (LARGE PLAGE DE PORTS)
    # ==========================================================================
    def _build_client_tab(self):
        tab = self.tab_client
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        top_bar = ctk.CTkFrame(tab, corner_radius=10)
        top_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 6))
        top_bar.grid_columnconfigure(0, weight=1)

        self.scan_btn = ctk.CTkButton(
            top_bar, text="🔍 Scanner tout le réseau local", height=38,
            font=ctk.CTkFont(size=14, weight="bold"), command=self._start_scan
        )
        self.scan_btn.pack(side="left", padx=12, pady=10, fill="x", expand=True)

        btn_adv = ctk.CTkButton(
            top_bar, text="⚙️ Avancé...", width=100, height=38,
            fg_color=("gray75", "gray25"), text_color=("black", "white"),
            command=lambda: AdvancedOptionsModal(self, on_connect_manual=self._manual_connect)
        )
        btn_adv.pack(side="right", padx=(0, 12), pady=10)

        self.progress_bar = ctk.CTkProgressBar(tab, height=4)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="sew", padx=10, pady=0)

        self.servers_scroll = ctk.CTkScrollableFrame(tab, label_text="Appareils détectés sur votre réseau Wi-Fi / LAN")
        self.servers_scroll.grid(row=2, column=0, sticky="nsew", padx=8, pady=(6, 6))

        self._refresh_servers_list()

    def _start_scan(self):
        if self._is_scanning:
            return

        self._is_scanning = True
        self.scan_btn.configure(state="disabled", text="Scan du réseau en cours...")
        self.progress_bar.set(0)
        self.status_lbl.configure(text="Balayage étendu des ports (20-30, 2121-2130, 2221-2230, 8080-8095)...")

        def worker():
            results = run_expanded_scan(progress_cb=lambda d, t: self.after(0, lambda: self.progress_bar.set(d / t if t else 0)))
            self.after(0, lambda: self._on_scan_completed(results))

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_completed(self, results: List[DetectedServer]):
        self._is_scanning = False
        self.scan_btn.configure(state="normal", text="🔍 Scanner tout le réseau local")
        self.progress_bar.set(1.0)
        self.status_lbl.configure(text=f"Scan terminé : {len(results)} appareil(s) trouvé(s).")

        current_keys = {(s.ip, s.port) for s in self.detected_servers}
        for r in results:
            if (r.ip, r.port) not in current_keys:
                self.detected_servers.append(r)
        self._refresh_servers_list()

    def _on_mdns_found(self, server: DetectedServer):
        def _add():
            if not any(s.ip == server.ip and s.port == server.port for s in self.detected_servers):
                self.detected_servers.insert(0, server)
                self._refresh_servers_list()
                self.status_lbl.configure(text=f"Nouvel appareil en ligne : {server.server_name or server.ip}")
        self.after(0, _add)

    def _refresh_servers_list(self):
        for w in self.servers_scroll.winfo_children():
            w.destroy()

        favs = FavoritesManager.load()
        fav_servers = [
            DetectedServer(
                ip=f["ip"], port=f["port"], protocol=f["protocol"],
                is_anonymous=f.get("is_anonymous", False),
                server_name=f.get("server_name", ""),
                banner=f.get("banner", "Favori")
            ) for f in favs
        ]

        if fav_servers:
            ctk.CTkLabel(self.servers_scroll, text="⭐ Vos Favoris", font=ctk.CTkFont(size=13, weight="bold"), text_color="#eab308", anchor="w").pack(fill="x", padx=6, pady=(4, 2))
            for s in fav_servers:
                self._render_card(s, is_pinned=True)

        other_servers = [s for s in self.detected_servers if not any(f["ip"] == s.ip and f["port"] == s.port for f in favs)]

        if other_servers or not fav_servers:
            title_text = "📡 Appareils détectés sur le réseau" if fav_servers else ""
            if title_text:
                ctk.CTkLabel(self.servers_scroll, text=title_text, font=ctk.CTkFont(size=13, weight="bold"), anchor="w").pack(fill="x", padx=6, pady=(8, 2))

        if not other_servers and not fav_servers:
            box = ctk.CTkFrame(self.servers_scroll, fg_color="transparent")
            box.pack(expand=True, fill="both", pady=80)
            ctk.CTkLabel(box, text="📡", font=ctk.CTkFont(size=44)).pack(pady=(0, 6))
            ctk.CTkLabel(box, text="Aucun ordinateur détecté pour le moment.", font=ctk.CTkFont(size=14, weight="bold")).pack()
            ctk.CTkLabel(box, text="Cliquez sur 'Scanner tout le réseau local' pour lancer la recherche.", font=ctk.CTkFont(size=12), text_color=("gray40", "gray65")).pack(pady=(2, 0))
            return

        for s in other_servers:
            self._render_card(s, is_pinned=False)

    def _render_card(self, s: DetectedServer, is_pinned: bool = False):
        card = ctk.CTkFrame(self.servers_scroll, corner_radius=8)
        card.pack(fill="x", pady=4, padx=4)
        card.grid_columnconfigure(1, weight=1)

        icon = "💻" if s.is_mdns or s.protocol == "FTP" else ("📱" if s.protocol == "HTTP" else "🔒")
        lbl_icon = ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=22), width=34)
        lbl_icon.grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=8)

        friendly_title = s.server_name if s.server_name else (s.banner or "Ordinateur distant")
        lbl_title = ctk.CTkLabel(card, text=friendly_title, font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
        lbl_title.grid(row=0, column=1, sticky="w", padx=4, pady=(6, 0))

        sub = f"{s.protocol} • {s.ip}:{s.port} • {'Accès libre' if s.is_anonymous else 'Mot de passe requis'}"
        lbl_sub = ctk.CTkLabel(card, text=sub, font=ctk.CTkFont(size=11), text_color=("gray45", "gray70"), anchor="w")
        lbl_sub.grid(row=1, column=1, sticky="w", padx=4, pady=(0, 6))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=2, padx=10, pady=6, sticky="e")

        star_color = "#eab308" if is_pinned or FavoritesManager.is_favorite(s) else ("gray60", "gray40")
        ctk.CTkButton(actions, text="★", width=30, height=30, fg_color="transparent", text_color=star_color, font=ctk.CTkFont(size=16), command=lambda srv=s: (FavoritesManager.toggle(srv), self._refresh_servers_list())).pack(side="left", padx=2)

        btn_txt = "🌐 Ouvrir Web" if s.protocol == "HTTP" else "🚀 Ouvrir les Fichiers"
        ctk.CTkButton(actions, text=btn_txt, height=32, command=lambda srv=s: self._open_server(srv)).pack(side="left", padx=4)

    def _open_server(self, server: DetectedServer):
        ok, msg = open_in_native_file_manager(ip=server.ip, port=server.port, protocol=server.protocol)
        if not ok:
            messagebox.showerror("Erreur", msg)

    def _manual_connect(self, ip, port, proto, user, pwd):
        ok, msg = open_in_native_file_manager(ip=ip, port=port, protocol=proto, user=user, password=pwd)
        if not ok:
            messagebox.showerror("Erreur", msg)

    # ==========================================================================
    # ONGLET 2 : PARTAGER AVEC NOM PERSONNALISÉ
    # ==========================================================================
    def _build_server_tab(self):
        tab = self.tab_server
        tab.grid_columnconfigure(0, weight=1)

        # 1. Nom du partage et Sélection du dossier
        box_dir = ctk.CTkFrame(tab, corner_radius=10)
        box_dir.pack(fill="x", padx=16, pady=(12, 6))
        box_dir.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(box_dir, text="Nom de votre partage :", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=14, pady=(12, 6), sticky="w")
        self.server_name_entry = ctk.CTkEntry(box_dir, height=32)
        self.server_name_entry.insert(0, socket.gethostname())
        self.server_name_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 14), pady=(12, 6))

        ctk.CTkLabel(box_dir, text="Dossier à partager :", font=ctk.CTkFont(size=13, weight="bold")).grid(row=1, column=0, padx=14, pady=(6, 12), sticky="w")
        def_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.exists(def_dir):
            def_dir = os.path.expanduser("~")

        self.server_dir_entry = ctk.CTkEntry(box_dir, height=32)
        self.server_dir_entry.insert(0, def_dir)
        self.server_dir_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 12))

        ctk.CTkButton(box_dir, text="📁 Choisir...", width=95, height=32, command=self._choose_server_dir).grid(row=1, column=2, padx=(2, 14), pady=(6, 12))

        # 2. Options de partage
        box_opts = ctk.CTkFrame(tab, corner_radius=10)
        box_opts.pack(fill="x", padx=16, pady=6)
        box_opts.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(box_opts, text="Partager pour :", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=14, pady=10, sticky="w")
        self.server_mode_seg = ctk.CTkSegmentedButton(
            box_opts,
            values=["💻 Autres Ordinateurs (Explorateur)", "📱 Smartphones & Navigateurs (Web)"]
        )
        self.server_mode_seg.set("💻 Autres Ordinateurs (Explorateur)")
        self.server_mode_seg.grid(row=0, column=1, padx=12, pady=10, sticky="ew")

        self.protect_var = ctk.BooleanVar(value=False)
        self.chk_protect = ctk.CTkCheckBox(box_opts, text="Protéger par un mot de passe (optionnel)", variable=self.protect_var, command=self._toggle_auth_fields)
        self.chk_protect.grid(row=1, column=0, columnspan=2, padx=14, pady=(6, 8), sticky="w")

        self.auth_fields_box = ctk.CTkFrame(box_opts, fg_color="transparent")
        self.auth_fields_box.grid(row=2, column=0, columnspan=2, padx=14, pady=(0, 10), sticky="w")

        ctk.CTkLabel(self.auth_fields_box, text="Nom :").pack(side="left", padx=(0, 4))
        self.srv_user_entry = ctk.CTkEntry(self.auth_fields_box, width=120)
        self.srv_user_entry.insert(0, "partage")
        self.srv_user_entry.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(self.auth_fields_box, text="Mot de passe :").pack(side="left", padx=(0, 4))
        self.srv_pwd_entry = ctk.CTkEntry(self.auth_fields_box, width=120, show="*")
        self.srv_pwd_entry.insert(0, "1234")
        self.srv_pwd_entry.pack(side="left")

        self._toggle_auth_fields()

        # 3. Bouton Démarrer / Arrêter
        self.btn_toggle_server = ctk.CTkButton(
            tab, text="▶ Démarrer le partage", font=ctk.CTkFont(size=16, weight="bold"),
            height=44, fg_color="#16a34a", hover_color="#15803d", command=self._toggle_server
        )
        self.btn_toggle_server.pack(fill="x", padx=16, pady=10)

        # 4. Carte active
        self.card_active = ctk.CTkFrame(tab, corner_radius=10)
        self.card_active.pack(fill="both", expand=True, padx=16, pady=(4, 10))

        self.lbl_server_state = ctk.CTkLabel(self.card_active, text="🔴 Aucun partage en cours", font=ctk.CTkFont(size=14, weight="bold"), text_color=("gray40", "gray65"))
        self.lbl_server_state.pack(pady=(12, 2))

        self.lbl_server_url = ctk.CTkLabel(self.card_active, text="--", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_server_url.pack(pady=2)

        btn_actions = ctk.CTkFrame(self.card_active, fg_color="transparent")
        btn_actions.pack(pady=4)

        self.btn_copy_url = ctk.CTkButton(btn_actions, text="📋 Copier le lien", width=120, height=28, state="disabled", command=self._copy_server_url)
        self.btn_copy_url.pack(side="left", padx=4)

        self.btn_test_local = ctk.CTkButton(btn_actions, text="🚀 Ouvrir mon dossier", width=160, height=28, state="disabled", command=self._open_local_server_in_os)
        self.btn_test_local.pack(side="left", padx=4)

        self.qr_label = ctk.CTkLabel(self.card_active, text="Le QR Code apparaîtra ici\npour connecter un smartphone.", font=ctk.CTkFont(size=12), text_color=("gray50", "gray60"))
        self.qr_label.pack(expand=True, pady=10)

    def _choose_server_dir(self):
        ch = filedialog.askdirectory(initialdir=self.server_dir_entry.get())
        if ch:
            self.server_dir_entry.delete(0, "end")
            self.server_dir_entry.insert(0, ch)

    def _toggle_auth_fields(self):
        if self.protect_var.get():
            self.auth_fields_box.grid()
        else:
            self.auth_fields_box.grid_remove()

    def _toggle_server(self):
        if self.server_ctrl.is_running:
            self.server_ctrl.stop()
            self.mdns_manager.unregister_server()

            self.btn_toggle_server.configure(text="▶ Démarrer le partage", fg_color="#16a34a", hover_color="#15803d")
            self.lbl_server_state.configure(text="🔴 Partage arrêté", text_color=("gray40", "gray65"))
            self.lbl_server_url.configure(text="--")
            self.btn_copy_url.configure(state="disabled")
            self.btn_test_local.configure(state="disabled")
            self.qr_label.configure(image="", text="Le QR Code apparaîtra ici\npour connecter un smartphone.")
            self.status_lbl.configure(text="Partage arrêté.")
        else:
            folder = self.server_dir_entry.get().strip()
            if not os.path.exists(folder):
                messagebox.showerror("Erreur", "Le dossier spécifié n'existe pas.")
                return

            server_name = self.server_name_entry.get().strip() or socket.gethostname()
            is_web = "Smartphones" in self.server_mode_seg.get()
            mode = "HTTP" if is_web else "FTP"
            port = 8080 if is_web else 2121

            user = self.srv_user_entry.get().strip() if self.protect_var.get() else None
            pwd = self.srv_pwd_entry.get().strip() if self.protect_var.get() else None

            try:
                self.server_ctrl.start(
                    mode=mode, server_name=server_name, folder=folder,
                    port=port, user=user, pwd=pwd, allow_write=True
                )
                url = self.server_ctrl.get_url()

                anon = (user is None)
                self.mdns_manager.register_server(
                    ip=self.server_ctrl.display_ip, port=port, protocol=mode,
                    server_name=server_name, is_anonymous=anon
                )

                self.btn_toggle_server.configure(text="⏹ Arrêter le partage", fg_color="#dc2626", hover_color="#b91c1c")
                self.lbl_server_state.configure(text=f"🟢 {server_name} est en ligne !", text_color="#16a34a")
                self.lbl_server_url.configure(text=url)
                self.btn_copy_url.configure(state="normal")
                self.btn_test_local.configure(state="normal")

                if mode == "HTTP":
                    self.btn_test_local.configure(text="🌐 Voir dans le Navigateur")
                else:
                    self.btn_test_local.configure(text="📁 Ouvrir l'Explorateur")

                self._generate_qr_code(url)
                self.status_lbl.configure(text=f"Partage en ligne : {server_name} ({url})")

            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de démarrer le partage :\n{e}")

    def _generate_qr_code(self, url: str):
        if not HAS_QRCODE:
            self.qr_label.configure(text=f"Lien : {url}\n(Installez 'qrcode' pour afficher le QR code)")
            return
        try:
            qr = qrcode.QRCode(box_size=4, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(140, 140))
            self.qr_label.configure(image=ctk_img, text="")
        except Exception:
            self.qr_label.configure(text=url)

    def _copy_server_url(self):
        url = self.lbl_server_url.cget("text")
        if url and url != "--":
            self.clipboard_clear()
            self.clipboard_append(url)
            messagebox.showinfo("Copié", f"Lien copié dans le presse-papier :\n{url}")

    def _open_local_server_in_os(self):
        if not self.server_ctrl.is_running:
            return
        if self.server_ctrl.mode == "HTTP":
            webbrowser.open(self.server_ctrl.get_url())
        else:
            open_in_native_file_manager(
                ip="127.0.0.1", port=self.server_ctrl.port, protocol="FTP",
                user=self.server_ctrl.user, password=self.server_ctrl.password
            )

    # ==========================================================================
    # 7. GESTION DE FERMETURE SÉCURISÉE & THÈME
    # ==========================================================================
    def _init_systray(self):
        if not HAS_SYSTRAY:
            return
        try:
            img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse((4, 4, 60, 60), fill="#2563eb", outline="#60a5fa", width=2)
            draw.text((18, 16), "FS", fill="white")

            menu = pystray.Menu(
                pystray.MenuItem("Afficher FTPStudio", lambda: self.after(0, lambda: (self.deiconify(), self.lift())), default=True),
                pystray.MenuItem("Quitter", self._quit_app)
            )
            self.tray_icon = pystray.Icon("FTPStudio", img, "FTPStudio", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception:
            self.tray_icon = None

    def _toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        ctk.set_appearance_mode(self.current_theme)
        self.theme_btn.configure(text="☀️" if self.current_theme == "light" else "🌙")

    def _on_window_close(self):
        """Gestion propre du clic sur la croix [X]."""
        if self.server_ctrl.is_running:
            rep = messagebox.askyesnocancel(
                "Fermeture",
                "Un partage est actuellement actif sur votre réseau.\n\n"
                "• OUI : Quitter complètement l'application\n"
                "• NON : Réduire en arrière-plan\n"
                "• ANNULER : Rester sur l'application"
            )
            if rep is True:
                self._quit_app()
            elif rep is False and self.tray_icon:
                self.withdraw()
        else:
            self._quit_app()

    def _quit_app(self):
        """Fermeture complète garantie de tous les processus et serveurs."""
        self.server_ctrl.stop()
        self.mdns_manager.close()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.destroy()
        sys.exit(0)


if __name__ == "__main__":
    app = FTPStudioApp()
    app.mainloop()