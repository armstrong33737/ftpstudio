"""
ftp_client.py
=============
Module FTP : connexion, navigation, téléchargement, téléversement et création de dossier.
"""

import ftplib
import io
import os
from dataclasses import dataclass
from typing import Callable, List, Optional


class FTPConnectionError(Exception):
    pass


@dataclass(frozen=True)
class FTPEntry:
    """Représente un fichier ou dossier distant (hachable pour set/dict)."""
    name: str
    is_dir: bool
    size: int = 0
    raw_type: str = ""


def sanitize_ftp_path(base: str, filename: str = "") -> str:
    """Évite les doubles slashs // qui font planter certains serveurs FTP."""
    base = base.strip()
    if not base or base == "/":
        return f"/{filename.lstrip('/')}" if filename else "/"
    return f"{base.rstrip('/')}/{filename.lstrip('/')}" if filename else base


def connect(
    ip: str,
    port: int = 21,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 5.0,
) -> ftplib.FTP:
    ftp = ftplib.FTP()
    try:
        ftp.connect(ip, int(port), timeout=timeout)
    except OSError as e:
        raise FTPConnectionError(f"Serveur {ip}:{port} inaccessible ({e})")

    try:
        if username:
            ftp.login(user=username, passwd=password or "")
        else:
            ftp.login(user="anonymous", passwd="anonymous@")
    except ftplib.error_perm as e:
        ftp.close()
        raise FTPConnectionError(f"Accès refusé sur {ip}:{port} - Identifiants requis ({e})")
    except Exception as e:
        ftp.close()
        raise FTPConnectionError(f"Erreur de connexion à {ip}:{port} ({e})")

    return ftp


def disconnect(ftp: Optional[ftplib.FTP]) -> None:
    if not ftp:
        return
    try:
        ftp.quit()
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass


def list_directory(ftp: ftplib.FTP, path: str = "/") -> List[FTPEntry]:
    entries: List[FTPEntry] = []
    try:
        original_dir = ftp.pwd()
    except Exception:
        original_dir = "/"

    safe_path = sanitize_ftp_path(path)
    try:
        ftp.cwd(safe_path)
    except ftplib.error_perm as e:
        raise FTPConnectionError(f"Impossible d'accéder à '{safe_path}' ({e})")

    try:
        # 1. Essai moderne via MLSD
        try:
            for name, facts in ftp.mlsd():
                if name in (".", ".."):
                    continue
                entry_type = facts.get("type", "file")
                is_dir = entry_type in ("dir", "cdir", "pdir")
                size_str = facts.get("size", "0")
                size = int(size_str) if size_str.isdigit() else 0
                entries.append(FTPEntry(name=name, is_dir=is_dir, size=size, raw_type=entry_type))
        except (ftplib.error_perm, AttributeError):
            # 2. Repli classique via LIST
            lines: List[str] = []
            ftp.retrlines("LIST", lines.append)
            for line in lines:
                parts = line.split(maxsplit=8)
                if len(parts) < 9:
                    continue
                perms, size_str, name = parts[0], parts[4], parts[8]
                if name in (".", ".."):
                    continue
                is_dir = perms.startswith("d")
                size = int(size_str) if size_str.isdigit() else 0
                entries.append(FTPEntry(name=name, is_dir=is_dir, size=size, raw_type="dir" if is_dir else "file"))
    finally:
        try:
            ftp.cwd(original_dir)
        except Exception:
            pass

    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


def fetch_file_to_memory(ftp: ftplib.FTP, remote_path: str, max_size: int = 15 * 1024 * 1024) -> io.BytesIO:
    buf = io.BytesIO()

    def _chunk(data: bytes):
        if buf.tell() + len(data) > max_size:
            raise FTPConnectionError("Fichier supérieur à 15 Mo (trop lourd pour l'aperçu)")
        buf.write(data)

    safe_path = sanitize_ftp_path(remote_path)
    try:
        ftp.retrbinary(f"RETR {safe_path}", _chunk)
    except ftplib.all_errors as e:
        raise FTPConnectionError(f"Lecture impossible de '{safe_path}' ({e})")

    buf.seek(0)
    return buf


def download_file(
    ftp: ftplib.FTP,
    remote_path: str,
    local_path: str,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> None:
    safe_path = sanitize_ftp_path(remote_path)
    downloaded = 0
    try:
        with open(local_path, "wb") as f:
            def _write(chunk: bytes):
                nonlocal downloaded
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded)

            ftp.retrbinary(f"RETR {safe_path}", _write)
    except ftplib.all_errors as e:
        if os.path.exists(local_path):
            os.remove(local_path)
        raise FTPConnectionError(f"Échec de réception ({e})")


def upload_file(
    ftp: ftplib.FTP,
    local_path: str,
    remote_path: str,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> None:
    safe_path = sanitize_ftp_path(remote_path)
    sent = 0
    try:
        with open(local_path, "rb") as f:
            def _read(chunk: bytes):
                nonlocal sent
                sent += len(chunk)
                if progress_callback:
                    progress_callback(sent)

            ftp.storbinary(f"STOR {safe_path}", f, callback=_read)
    except ftplib.all_errors as e:
        raise FTPConnectionError(f"Échec d'envoi pour '{os.path.basename(local_path)}' ({e})")


def create_directory(ftp: ftplib.FTP, remote_path: str) -> None:
    safe_path = sanitize_ftp_path(remote_path)
    try:
        ftp.mkd(safe_path)
    except ftplib.all_errors as e:
        raise FTPConnectionError(f"Création de dossier impossible ({e})")