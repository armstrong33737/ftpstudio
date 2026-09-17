"""
remote_engine.py
================
Abstraction réseau multi-protocole (FTP, FTPS, SFTP) et moteur de transfert
Serveur-à-Serveur direct en mémoire (Stream Pipe sans disque local).
"""

import ftplib
import io
import os
import ssl
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, List, Optional

# Support optionnel de SFTP via paramiko
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False


@dataclass(frozen=True)
class RemoteEntry:
    """Entrée distante immuable et hachable."""
    name: str
    is_dir: bool
    size: int = 0
    raw_type: str = ""
    mtime: float = 0.0


def sanitize_remote_path(base: str, filename: str = "") -> str:
    """Normalise les chemins pour éviter les doublons de slashs '//'."""
    base = base.strip()
    if not base or base == "/":
        return f"/{filename.lstrip('/')}" if filename else "/"
    return f"{base.rstrip('/')}/{filename.lstrip('/')}" if filename else base


class RemoteSession(ABC):
    """Interface unifiée pour FTP, FTPS et SFTP."""

    def __init__(self, host: str, port: int, user: Optional[str], password: Optional[str]):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.is_connected = False

    @abstractmethod
    def connect(self, timeout: float = 6.0):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def list_dir(self, path: str = "/") -> List[RemoteEntry]:
        pass

    @abstractmethod
    def fetch_to_memory(self, remote_path: str, max_size: int = 15 * 1024 * 1024) -> io.BytesIO:
        pass

    @abstractmethod
    def download_file(self, remote_path: str, local_path: str, progress_cb=None, cancel_event=None):
        pass

    @abstractmethod
    def upload_file(self, local_path: str, remote_path: str, progress_cb=None, cancel_event=None):
        pass

    @abstractmethod
    def create_dir(self, path: str):
        pass

    @abstractmethod
    def delete_file(self, path: str):
        pass

    @abstractmethod
    def delete_dir_recursive(self, path: str):
        pass

    @abstractmethod
    def rename(self, old_path: str, new_path: str):
        pass

    @abstractmethod
    def keep_alive(self):
        pass

    @abstractmethod
    def open_read_stream(self, path: str):
        """Fournit un flux de lecture pour le streaming Serveur-à-Serveur."""
        pass

    @abstractmethod
    def write_stream_chunk(self, path: str, stream_callback: Callable):
        pass


# ------------------------------------------------------------------
# Implémentation FTP / FTPS
# ------------------------------------------------------------------
class FTPSession(RemoteSession):

    def __init__(self, host: str, port: int = 21, user: Optional[str] = None, password: Optional[str] = None, use_tls: bool = False):
        super().__init__(host, port, user, password)
        self.use_tls = use_tls
        self.ftp: Optional[ftplib.FTP] = None

    def connect(self, timeout: float = 6.0):
        if self.use_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            self.ftp = ftplib.FTP_TLS(context=context)
        else:
            self.ftp = ftplib.FTP()

        self.ftp.connect(self.host, int(self.port), timeout=timeout)
        if self.user:
            self.ftp.login(user=self.user, passwd=self.password or "")
        else:
            self.ftp.login(user="anonymous", passwd="anonymous@")

        if self.use_tls and isinstance(self.ftp, ftplib.FTP_TLS):
            self.ftp.prot_p()  # Sécurise le canal de données
        self.is_connected = True

    def disconnect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                try:
                    self.ftp.close()
                except Exception:
                    pass
        self.ftp = None
        self.is_connected = False

    def list_dir(self, path: str = "/") -> List[RemoteEntry]:
        safe = sanitize_remote_path(path)
        orig = "/"
        try:
            orig = self.ftp.pwd()
        except Exception:
            pass

        self.ftp.cwd(safe)
        entries: List[RemoteEntry] = []
        try:
            try:
                for name, facts in self.ftp.mlsd():
                    if name in (".", ".."):
                        continue
                    is_dir = facts.get("type", "file") in ("dir", "cdir", "pdir")
                    size = int(facts.get("size", "0")) if facts.get("size", "0").isdigit() else 0
                    entries.append(RemoteEntry(name=name, is_dir=is_dir, size=size, raw_type=facts.get("type", "")))
            except Exception:
                lines = []
                self.ftp.retrlines("LIST", lines.append)
                for line in lines:
                    p = line.split(maxsplit=8)
                    if len(p) >= 9:
                        name = p[8]
                        if name not in (".", ".."):
                            is_dir = p[0].startswith("d")
                            sz = int(p[4]) if p[4].isdigit() else 0
                            entries.append(RemoteEntry(name=name, is_dir=is_dir, size=sz, raw_type="dir" if is_dir else "file"))
        finally:
            try:
                self.ftp.cwd(orig)
            except Exception:
                pass

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def fetch_to_memory(self, remote_path: str, max_size: int = 15 * 1024 * 1024) -> io.BytesIO:
        safe = sanitize_remote_path(remote_path)
        buf = io.BytesIO()

        def _chunk(d):
            if buf.tell() + len(d) > max_size:
                raise Exception("Fichier supérieur à 15 Mo")
            buf.write(d)

        self.ftp.retrbinary(f"RETR {safe}", _chunk)
        buf.seek(0)
        return buf

    def download_file(self, remote_path: str, local_path: str, progress_cb=None, cancel_event=None):
        safe = sanitize_remote_path(remote_path)
        transferred = 0
        with open(local_path, "wb") as f:
            def _write(data):
                if cancel_event and cancel_event.is_set():
                    raise Exception("Transfert annulé par l'utilisateur")
                nonlocal transferred
                f.write(data)
                transferred += len(data)
                if progress_cb:
                    progress_cb(transferred)

            self.ftp.retrbinary(f"RETR {safe}", _write)

    def upload_file(self, local_path: str, remote_path: str, progress_cb=None, cancel_event=None):
        safe = sanitize_remote_path(remote_path)
        sent = 0
        with open(local_path, "rb") as f:
            def _read(data):
                if cancel_event and cancel_event.is_set():
                    raise Exception("Transfert annulé par l'utilisateur")
                nonlocal sent
                sent += len(data)
                if progress_cb:
                    progress_cb(sent)

            self.ftp.storbinary(f"STOR {safe}", f, callback=_read)

    def create_dir(self, path: str):
        self.ftp.mkd(sanitize_remote_path(path))

    def delete_file(self, path: str):
        self.ftp.delete(sanitize_remote_path(path))

    def delete_dir_recursive(self, path: str):
        safe = sanitize_remote_path(path)
        for item in self.list_dir(safe):
            sub = sanitize_remote_path(safe, item.name)
            if item.is_dir:
                self.delete_dir_recursive(sub)
            else:
                self.delete_file(sub)
        self.ftp.rmd(safe)

    def rename(self, old_path: str, new_path: str):
        self.ftp.rename(sanitize_remote_path(old_path), sanitize_remote_path(new_path))

    def keep_alive(self):
        if self.ftp and self.is_connected:
            try:
                self.ftp.voidcmd("NOOP")
            except Exception:
                pass

    def open_read_stream(self, path: str):
        safe = sanitize_remote_path(path)
        conn = self.ftp.transfercmd(f"RETR {safe}")
        return conn

    def write_stream_chunk(self, path: str, stream_callback: Callable):
        safe = sanitize_remote_path(path)
        self.ftp.storbinary(f"STOR {safe}", stream_callback)


# ------------------------------------------------------------------
# Implémentation SFTP (SSH)
# ------------------------------------------------------------------
class SFTPSession(RemoteSession):

    def __init__(self, host: str, port: int = 22, user: Optional[str] = None, password: Optional[str] = None):
        super().__init__(host, port, user, password)
        self.client = None
        self.sftp = None

    def connect(self, timeout: float = 6.0):
        if not HAS_PARAMIKO:
            raise Exception("Paramiko n'est pas installé. Exécutez : pip install paramiko")
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            self.host, port=int(self.port),
            username=self.user or "root", password=self.password,
            timeout=timeout, look_for_keys=False
        )
        self.sftp = self.client.open_sftp()
        self.is_connected = True

    def disconnect(self):
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.sftp = None
        self.client = None
        self.is_connected = False

    def list_dir(self, path: str = "/") -> List[RemoteEntry]:
        safe = sanitize_remote_path(path)
        entries = []
        import stat
        for attr in self.sftp.listdir_attr(safe):
            if attr.filename in (".", ".."):
                continue
            is_dir = stat.S_ISDIR(attr.st_mode)
            entries.append(RemoteEntry(
                name=attr.filename, is_dir=is_dir,
                size=attr.st_size if not is_dir else 0,
                raw_type="dir" if is_dir else "file",
                mtime=float(attr.st_mtime or 0)
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def fetch_to_memory(self, remote_path: str, max_size: int = 15 * 1024 * 1024) -> io.BytesIO:
        safe = sanitize_remote_path(remote_path)
        buf = io.BytesIO()
        with self.sftp.open(safe, "rb") as remote_file:
            data = remote_file.read(max_size + 1)
            if len(data) > max_size:
                raise Exception("Fichier supérieur à 15 Mo")
            buf.write(data)
        buf.seek(0)
        return buf

    def download_file(self, remote_path: str, local_path: str, progress_cb=None, cancel_event=None):
        safe = sanitize_remote_path(remote_path)
        def _cb(transferred, total):
            if cancel_event and cancel_event.is_set():
                raise Exception("Transfert annulé")
            if progress_cb:
                progress_cb(transferred)
        self.sftp.get(safe, local_path, callback=_cb)

    def upload_file(self, local_path: str, remote_path: str, progress_cb=None, cancel_event=None):
        safe = sanitize_remote_path(remote_path)
        def _cb(transferred, total):
            if cancel_event and cancel_event.is_set():
                raise Exception("Transfert annulé")
            if progress_cb:
                progress_cb(transferred)
        self.sftp.put(local_path, safe, callback=_cb)

    def create_dir(self, path: str):
        self.sftp.mkdir(sanitize_remote_path(path))

    def delete_file(self, path: str):
        self.sftp.remove(sanitize_remote_path(path))

    def delete_dir_recursive(self, path: str):
        safe = sanitize_remote_path(path)
        for item in self.list_dir(safe):
            sub = sanitize_remote_path(safe, item.name)
            if item.is_dir:
                self.delete_dir_recursive(sub)
            else:
                self.delete_file(sub)
        self.sftp.rmdir(safe)

    def rename(self, old_path: str, new_path: str):
        self.sftp.rename(sanitize_remote_path(old_path), sanitize_remote_path(new_path))

    def keep_alive(self):
        if self.client and self.is_connected:
            try:
                transport = self.client.get_transport()
                if transport:
                    transport.send_ignore()
            except Exception:
                pass

    def open_read_stream(self, path: str):
        return self.sftp.open(sanitize_remote_path(path), "rb")

    def write_stream_chunk(self, path: str, stream_callback: Callable):
        with self.sftp.open(sanitize_remote_path(path), "wb") as remote_file:
            while True:
                chunk = stream_callback(64 * 1024)
                if not chunk:
                    break
                remote_file.write(chunk)


# ------------------------------------------------------------------
# Moteur de Streaming Serveur-à-Serveur (Sans disque)
# ------------------------------------------------------------------
def transfer_server_to_server(
    src_session: RemoteSession, src_path: str,
    dst_session: RemoteSession, dst_path: str,
    file_size: int, progress_cb=None, cancel_event=None
):
    """Transfère un flux directement de src à dst via un buffer RAM."""
    buf_size = 128 * 1024
    transferred = 0

    if isinstance(src_session, SFTPSession) and isinstance(dst_session, SFTPSession):
        with src_session.sftp.open(sanitize_remote_path(src_path), "rb") as r:
            with dst_session.sftp.open(sanitize_remote_path(dst_path), "wb") as w:
                while True:
                    if cancel_event and cancel_event.is_set():
                        raise Exception("Transfert annulé")
                    chunk = r.read(buf_size)
                    if not chunk:
                        break
                    w.write(chunk)
                    transferred += len(chunk)
                    if progress_cb:
                        progress_cb(transferred)
    else:
        # Solution universelle via BytesIO / flux mémoires tamponnés
        mem_buf = src_session.fetch_to_memory(src_path, max_size=max(file_size + 1024, 50 * 1024 * 1024))
        if isinstance(dst_session, FTPSession):
            dst_session.ftp.storbinary(f"STOR {sanitize_remote_path(dst_path)}", mem_buf)
        elif isinstance(dst_session, SFTPSession):
            dst_session.sftp.putfo(mem_buf, sanitize_remote_path(dst_path))
        if progress_cb:
            progress_cb(file_size)