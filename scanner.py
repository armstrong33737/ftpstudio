"""
scanner.py
==========
Scan multi-ports multithreadé (FTP 21, SFTP 22, FTPS 990), détection de bannières
et test d'accès anonyme en tâche de fond.
"""

import socket
import ipaddress
import ftplib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass(frozen=True)
class DetectedServer:
    ip: str
    port: int
    protocol: str       # "FTP", "SFTP" ou "FTPS"
    is_anonymous: bool  # Vrai si ouvert sans mot de passe
    banner: str = ""    # Version / démon hôte

    def __str__(self):
        return f"{self.protocol}://{self.ip}:{self.port}"


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = socket.gethostbyname(socket.gethostname())
    finally:
        s.close()
    return ip


def get_network_range(local_ip: str, prefix: int = 24) -> List[str]:
    net = ipaddress.ip_network(f"{local_ip}/{prefix}", strict=False)
    return [str(ip) for ip in net.hosts()]


def _probe_host_port(ip: str, port: int, timeout: float = 0.3) -> Optional[DetectedServer]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            if sock.connect_ex((ip, port)) != 0:
                return None

            # Identification du protocole
            protocol = "FTP"
            if port == 22 or port == 2222:
                protocol = "SFTP"
            elif port == 990:
                protocol = "FTPS"

            banner = ""
            is_anon = False

            # Test de bannière et d'accès anonyme rapide pour le FTP
            if protocol in ("FTP", "FTPS"):
                try:
                    f = ftplib.FTP()
                    f.connect(ip, port, timeout=0.6)
                    banner = f.getwelcome().strip().splitlines()[0][:40]
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
                    banner = "SSH-2.0"

            return DetectedServer(ip=ip, port=port, protocol=protocol, is_anonymous=is_anon, banner=banner)
    except Exception:
        return None


def scan_network(
    ports: Optional[List[int]] = None,
    custom_cidr: Optional[str] = None,
    max_workers: int = 150,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> List[DetectedServer]:
    if not ports:
        ports = [21, 22, 990]

    local_ip = get_local_ip()
    if custom_cidr:
        net = ipaddress.ip_network(custom_cidr, strict=False)
        ip_list = [str(ip) for ip in net.hosts()]
    else:
        ip_list = get_network_range(local_ip)

    tasks = [(ip, p) for ip in ip_list for p in ports]
    total = len(tasks)
    done = 0
    results: List[DetectedServer] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_probe_host_port, ip, port): (ip, port) for ip, port in tasks}
        for future in as_completed(futures):
            done += 1
            res = future.result()
            if res:
                results.append(res)
            if progress_callback:
                progress_callback(done, total)

    results.sort(key=lambda s: (tuple(int(x) for x in s.ip.split(".")), s.port))
    return results


def parse_ports_input(raw: str) -> List[int]:
    ports = []
    for part in raw.split(","):
        p = part.strip()
        if p.isdigit() and 1 <= int(p) <= 65535:
            ports.append(int(p))
    return ports or [21, 22, 990]