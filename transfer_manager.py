"""
transfer_manager.py
===================
Gestionnaire de file d'attente multithreadé optimisé.
Régule les notifications vers l'UI (throttling à 10 Hz) pour supprimer
toute saturation de la boucle d'événements Tkinter.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from remote_engine import RemoteSession, transfer_server_to_server


@dataclass
class TransferTask:
    id: str
    name: str
    src_desc: str
    dst_desc: str
    total_bytes: int
    transferred_bytes: int = 0
    speed: float = 0.0
    eta: float = 0.0
    status: str = "queued"
    error_msg: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)

    kind: str = "download"
    session_src: Optional[RemoteSession] = None
    session_dst: Optional[RemoteSession] = None
    src_path: str = ""
    dst_path: str = ""


class TransferManager:

    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self.tasks: List[TransferTask] = []
        self._lock = threading.Lock()
        self._running = True
        self.on_update: Optional[Callable] = None
        self._last_notify_time = 0.0  # Pour le throttling

        self._worker_thread = threading.Thread(target=self._queue_loop, daemon=True)
        self._worker_thread.start()

    def add_download(self, session: RemoteSession, remote_path: str, local_path: str, file_name: str, size: int):
        task = TransferTask(
            id=str(uuid.uuid4())[:8],
            name=file_name,
            src_desc=f"{session.host}:{remote_path}",
            dst_desc=local_path,
            total_bytes=size,
            kind="download",
            session_src=session,
            src_path=remote_path,
            dst_path=local_path
        )
        with self._lock:
            self.tasks.append(task)
        self._notify_force()

    def add_upload(self, session: RemoteSession, local_path: str, remote_path: str, file_name: str, size: int):
        task = TransferTask(
            id=str(uuid.uuid4())[:8],
            name=file_name,
            src_desc=local_path,
            dst_desc=f"{session.host}:{remote_path}",
            total_bytes=size,
            kind="upload",
            session_dst=session,
            src_path=local_path,
            dst_path=remote_path
        )
        with self._lock:
            self.tasks.append(task)
        self._notify_force()

    def add_server_to_server(self, src_s: RemoteSession, src_p: str, dst_s: RemoteSession, dst_p: str, name: str, size: int):
        task = TransferTask(
            id=str(uuid.uuid4())[:8],
            name=name,
            src_desc=f"{src_s.host}:{src_p}",
            dst_desc=f"{dst_s.host}:{dst_p}",
            total_bytes=size,
            kind="s2s",
            session_src=src_s,
            session_dst=dst_s,
            src_path=src_p,
            dst_path=dst_p
        )
        with self._lock:
            self.tasks.append(task)
        self._notify_force()

    def cancel_task(self, task_id: str):
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    t.cancel_event.set()
                    t.status = "cancelled"
                    break
        self._notify_force()

    def clear_finished(self):
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status in ("queued", "running")]
        self._notify_force()

    def get_summary(self):
        with self._lock:
            running = [t for t in self.tasks if t.status == "running"]
            queued = [t for t in self.tasks if t.status == "queued"]
            total_speed = sum(t.speed for t in running)
            return len(running) + len(queued), total_speed

    def _queue_loop(self):
        while self._running:
            time.sleep(0.3)
            with self._lock:
                active_count = len([t for t in self.tasks if t.status == "running"])
                if active_count >= self.max_concurrent:
                    continue
                next_task = next((t for t in self.tasks if t.status == "queued"), None)
                if not next_task:
                    continue
                next_task.status = "running"

            threading.Thread(target=self._run_task, args=(next_task,), daemon=True).start()

    def _run_task(self, task: TransferTask):
        last_time = time.time()
        last_bytes = 0

        def _progress(current_bytes):
            nonlocal last_time, last_bytes
            now = time.time()
            dt = now - last_time
            if dt >= 0.3:
                delta = current_bytes - last_bytes
                task.speed = max(0.0, delta / dt)
                rem = max(0, task.total_bytes - current_bytes)
                task.eta = rem / task.speed if task.speed > 0 else 0.0
                last_time = now
                last_bytes = current_bytes
            task.transferred_bytes = current_bytes
            self._notify_throttled()

        try:
            if task.kind == "download":
                task.session_src.download_file(task.src_path, task.dst_path, _progress, task.cancel_event)
            elif task.kind == "upload":
                task.session_dst.upload_file(task.src_path, task.dst_path, _progress, task.cancel_event)
            elif task.kind == "s2s":
                transfer_server_to_server(task.session_src, task.src_path, task.session_dst, task.dst_path, task.total_bytes, _progress, task.cancel_event)

            task.status = "completed"
            task.transferred_bytes = task.total_bytes
        except Exception as e:
            task.status = "cancelled" if task.cancel_event.is_set() else "failed"
            task.error_msg = str(e)
        finally:
            self._notify_force()

    def _notify_throttled(self):
        """Limite les notifications à 10 Hz pour libérer le thread graphique."""
        now = time.time()
        if now - self._last_notify_time >= 0.1:
            self._last_notify_time = now
            if self.on_update:
                self.on_update()

    def _notify_force(self):
        self._last_notify_time = time.time()
        if self.on_update:
            self.on_update()