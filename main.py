"""
main.py
=======
Interface GNOME Files optimisée :
- Cases à cocher dédiées sur chaque élément pour la sélection multiple
- Défilement (scroll) 100% fiable et universel (molette active partout)
- Cache mémoire instantané (0 ms)
- Double-clic : ouverture immédiate avec le logiciel par défaut
- Mode Clair et Sombre parfaitement contrastés
"""

import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from typing import Dict, List, Optional, Set

import customtkinter as ctk

import remote_engine
import scanner
from remote_engine import FTPSession, RemoteEntry, SFTPSession, sanitize_remote_path
from transfer_manager import TransferManager
from ui_components import ContextMenu, TransferDashboardModal

# Support Drag-and-Drop OS natif
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    class BaseAppClass(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
    HAS_TKDND = True
except ImportError:
    BaseAppClass = ctk.CTk
    HAS_TKDND = False

FILE_ICONS = {
    "pdf": "📕", "png": "🖼", "jpg": "🖼", "jpeg": "🖼", "webp": "🖼", "gif": "🖼",
    "mp4": "🎬", "mkv": "🎬", "avi": "🎬", "mp3": "🎵", "wav": "🎵", "flac": "🎵",
    "zip": "📦", "tar": "📦", "gz": "📦", "7z": "📦", "rar": "📦",
    "py": "🐍", "json": "📜", "txt": "📄", "md": "📝", "csv": "📊", "html": "🌐"
}

CARD_WIDTH = 104
CARD_HEIGHT = 116


class AnimatedSpinner(ctk.CTkCanvas):
    """Spinner vectoriel fluide."""

    def __init__(self, master, size=28, **kwargs):
        super().__init__(master, width=size, height=size, highlightthickness=0, **kwargs)
        self.size = size
        self.angle = 0
        self._is_running = False
        self._after_id = None
        self.update_theme("dark")

    def update_theme(self, mode: str):
        bg = "#242424" if mode == "dark" else "#ebebeb"
        self.arc_color = "#3b82f6" if mode == "dark" else "#2563eb"
        self.configure(bg=bg)

    def start(self):
        if not self._is_running:
            self._is_running = True
            self._animate()

    def stop(self):
        self._is_running = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        self.delete("all")

    def _animate(self):
        if not self._is_running:
            return
        self.delete("all")
        cx = cy = self.size / 2
        r = (self.size / 2) - 4
        self.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=self.angle, extent=100,
            outline=self.arc_color, width=3, style=tk.ARC
        )
        self.angle = (self.angle + 24) % 360
        self._after_id = self.after(35, self._animate)


class FTPScannerApp(BaseAppClass):

    def __init__(self):
        super().__init__()

        self.title("Explorateur Réseau & Client FTP (GNOME Files)")
        self.geometry("1340x780")
        self.minsize(1050, 620)

        self.current_theme = "dark"
        ctk.set_appearance_mode(self.current_theme)
        ctk.set_default_color_theme("dark-blue")

        self.current_session: Optional[remote_engine.RemoteSession] = None
        self.current_host_info = None
        self.current_path = "/"
        self.history: List[str] = []
        self.forward_history: List[str] = []

        # Cache mémoire rapide
        self.folder_cache: Dict[str, List[RemoteEntry]] = {}

        # Fichiers & Sélection
        self.all_entries: List[RemoteEntry] = []
        self.filtered_entries: List[RemoteEntry] = []
        self.selected_entries: Set[RemoteEntry] = set()
        self.item_cards: Dict[RemoteEntry, ctk.CTkFrame] = {}
        self.item_checkboxes: Dict[RemoteEntry, ctk.CTkCheckBox] = {}

        self.view_mode = "grid"
        self.current_grid_cols = 10
        self._search_job = None
        self.items_container = None

        self.local_download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.exists(self.local_download_dir):
            self.local_download_dir = os.path.expanduser("~")

        self.transfers = TransferManager(max_concurrent=3)
        self.transfers.on_update = lambda: self.after(0, self._update_transfer_status)

        self.context_menu = ContextMenu(self, self._on_context_action)

        self._build_layout()
        self._setup_dnd()
        self._bind_shortcuts()

    # ================================================================
    # Layout GNOME Files
    # ================================================================
    def _build_layout(self):
        self.grid_columnconfigure(0, weight=0, minsize=310)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_explorer()

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, corner_radius=12)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        sidebar.grid_rowconfigure(2, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(sidebar, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        head.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            head, text="🌐 Réseau FTP", font=ctk.CTkFont(size=15, weight="bold"),
            text_color=("#0f172a", "#f8fafc")
        ).grid(row=0, column=0, sticky="w")

        btn_manual = ctk.CTkButton(
            head, text="🔑 Manuel", width=70, height=26,
            text_color=("#ffffff", "#ffffff"),
            command=self._open_manual_dialog
        )
        btn_manual.grid(row=0, column=1, sticky="e")

        scan_box = ctk.CTkFrame(sidebar, fg_color="transparent")
        scan_box.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        scan_box.grid_columnconfigure(0, weight=1)

        self.ports_entry = ctk.CTkEntry(scan_box, placeholder_text="21, 22, 990", height=28)
        self.ports_entry.insert(0, "21, 22")
        self.ports_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.scan_btn = ctk.CTkButton(scan_box, text="Scanner", width=75, height=28, command=self._start_scan)
        self.scan_btn.grid(row=0, column=1, sticky="e")

        self.scan_progress = ctk.CTkProgressBar(sidebar, height=4)
        self.scan_progress.set(0)
        self.scan_progress.grid(row=1, column=0, sticky="ew", padx=12, pady=(38, 4))

        self.hosts_scroll = ctk.CTkScrollableFrame(sidebar, label_text="Serveurs détectés")
        self.hosts_scroll.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_main_explorer(self):
        main = ctk.CTkFrame(self, corner_radius=12)
        main.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        main.grid_rowconfigure(2, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # Barre supérieure
        toolbar = ctk.CTkFrame(main, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        toolbar.grid_columnconfigure(3, weight=1)

        self.btn_back = ctk.CTkButton(toolbar, text="◀", width=34, height=32, command=self._nav_back, state="disabled")
        self.btn_back.grid(row=0, column=0, padx=(0, 2))

        self.btn_fwd = ctk.CTkButton(toolbar, text="▶", width=34, height=32, command=self._nav_fwd, state="disabled")
        self.btn_fwd.grid(row=0, column=1, padx=(0, 2))

        self.btn_up = ctk.CTkButton(toolbar, text="▲", width=34, height=32, command=self._nav_up, state="disabled")
        self.btn_up.grid(row=0, column=2, padx=(0, 8))

        self.path_entry = ctk.CTkEntry(toolbar, height=32, placeholder_text="Non connecté")
        self.path_entry.grid(row=0, column=3, sticky="ew", padx=(0, 8))
        self.path_entry.bind("<Return>", lambda e: self._on_path_entered())

        self.spinner = AnimatedSpinner(toolbar, size=28)
        self.spinner.grid(row=0, column=4, padx=(0, 8))
        self.spinner.update_theme(self.current_theme)

        self.btn_mkdir = ctk.CTkButton(toolbar, text="📁+ Dossier", width=90, height=32, command=self._on_mkdir, state="disabled")
        self.btn_mkdir.grid(row=0, column=5, padx=(0, 4))

        self.btn_upload = ctk.CTkButton(toolbar, text="⬆ Envoyer", width=85, height=32, command=self._on_upload_pick, state="disabled")
        self.btn_upload.grid(row=0, column=6, padx=(0, 6))

        self.view_seg = ctk.CTkSegmentedButton(toolbar, values=["🗂 Grille", "📋 Liste"], command=self._toggle_view, height=32)
        self.view_seg.set("🗂 Grille")
        self.view_seg.grid(row=0, column=7, padx=(0, 6))

        self.theme_btn = ctk.CTkButton(toolbar, text="🌙", width=34, height=32, command=self._toggle_theme)
        self.theme_btn.grid(row=0, column=8)

        # Sous-barre
        sub = ctk.CTkFrame(main, fg_color="transparent")
        sub.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 4))
        sub.grid_columnconfigure(2, weight=1)

        # Case à cocher "Tout sélectionner"
        self.chk_select_all = ctk.CTkCheckBox(
            sub, text="Tout cocher", width=20, height=20, checkbox_width=18, checkbox_height=18,
            command=self._on_select_all_checked
        )
        self.chk_select_all.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.selection_label = ctk.CTkLabel(
            sub, text="0 élément sélectionné", text_color=("#64748b", "#94a3b8"), font=ctk.CTkFont(size=12)
        )
        self.selection_label.grid(row=0, column=1, sticky="w")

        self.search_entry = ctk.CTkEntry(sub, placeholder_text="🔍 Filtrer...", width=160, height=26)
        self.search_entry.grid(row=0, column=2, sticky="w", padx=14)
        self.search_entry.bind("<KeyRelease>", self._on_search_key_release)

        local_target_box = ctk.CTkFrame(sub, fg_color="transparent")
        local_target_box.grid(row=0, column=3, sticky="e")

        self.lbl_local_dir = ctk.CTkLabel(
            local_target_box,
            text=f"📁 Dossier local : {os.path.basename(self.local_download_dir) or self.local_download_dir}",
            text_color=("#475569", "#94a3b8"),
            font=ctk.CTkFont(size=12)
        )
        self.lbl_local_dir.pack(side="left", padx=6)

        self.btn_ch_dir = ctk.CTkButton(
            local_target_box, text="Changer", width=68, height=24,
            fg_color=("gray90", "gray22"),
            text_color=("#0f172a", "#f8fafc"),
            border_color=("#cbd5e1", "#475569"),
            border_width=1,
            command=self._choose_local_dir
        )
        self.btn_ch_dir.pack(side="left", padx=4)

        self.btn_download = ctk.CTkButton(
            local_target_box, text="⬇ Télécharger la sélection", height=24,
            command=self._download_selected_to_target, state="disabled"
        )
        self.btn_download.pack(side="left", padx=(6, 0))

        # Zone des fichiers
        self.files_scroll = ctk.CTkScrollableFrame(main, label_text="Fichiers distants")
        self.files_scroll.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 6))
        self.files_scroll.bind("<Configure>", self._on_container_resized)

        # Barre de statut
        bottom_bar = ctk.CTkFrame(main, fg_color="transparent")
        bottom_bar.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 6))
        bottom_bar.grid_columnconfigure(0, weight=1)

        self.status_bar = ctk.CTkLabel(bottom_bar, text="Prêt.", anchor="w", text_color=("#64748b", "#94a3b8"))
        self.status_bar.grid(row=0, column=0, sticky="w")

        self.btn_dashboard = ctk.CTkButton(
            bottom_bar, text="📊 Transferts (0)", width=120, height=24,
            command=lambda: TransferDashboardModal(self, self.transfers)
        )
        self.btn_dashboard.grid(row=0, column=1, sticky="e")

    # ================================================================
    # Résolution Définitive du Scroll (Liaison Récursive)
    # ================================================================
    def _bind_mousewheel_recursive(self, widget):
        """Lie le scroll à tous les sous-composants pour qu'il ne bloque jamais."""
        widget.bind("<Button-4>", self._on_wheel_scroll, add="+")
        widget.bind("<Button-5>", self._on_wheel_scroll, add="+")
        widget.bind("<MouseWheel>", self._on_wheel_scroll, add="+")
        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child)

    def _on_wheel_scroll(self, event):
        if event.num == 4:
            self.files_scroll._parent_canvas.yview_scroll(-2, "units")
        elif event.num == 5:
            self.files_scroll._parent_canvas.yview_scroll(2, "units")
        elif event.delta:
            delta = -1 if event.delta > 0 else 1
            self.files_scroll._parent_canvas.yview_scroll(delta * 2, "units")

    # ================================================================
    # Drag and Drop OS
    # ================================================================
    def _setup_dnd(self):
        if HAS_TKDND:
            try:
                self.files_scroll.drop_target_register(DND_FILES)
                self.files_scroll.dnd_bind("<<Drop>>", self._on_dnd_drop)
                self.files_scroll._parent_canvas.drop_target_register(DND_FILES)
                self.files_scroll._parent_canvas.dnd_bind("<<Drop>>", self._on_dnd_drop)
            except Exception:
                pass

    def _on_dnd_drop(self, event):
        if not self.current_session:
            messagebox.showwarning("Attention", "Veuillez d'abord vous connecter à un serveur.")
            return
        files = self.tk.splitlist(event.data)
        valid = [f for f in files if os.path.exists(f)]
        if valid:
            self._start_upload_job(valid)

    # ================================================================
    # Raccourcis Clavier
    # ================================================================
    def _bind_shortcuts(self):
        self.bind("<Control-a>", lambda e: self._select_all_toggle(True))
        self.bind("<F2>", lambda e: self._rename_selected())
        self.bind("<Delete>", lambda e: self._delete_selected())
        self.bind("<BackSpace>", lambda e: self._nav_up())
        self.bind("<F5>", lambda e: self._refresh_current_folder(force_network=True))

    def _toggle_theme(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        self.btn_theme.configure(text="☀️" if self.theme_mode == "light" else "🌙")
        ctk.set_appearance_mode(self.theme_mode)
        self.spinner.update_theme(self.current_theme)
        self._refresh_all_visuals()

    def _toggle_view(self, mode):
        self.view_mode = "grid" if "Grille" in mode else "list"
        self._render_files_directly()

    def _choose_local_dir(self):
        ch = filedialog.askdirectory(initialdir=self.local_download_dir)
        if ch:
            self.local_download_dir = ch
            self.lbl_local_dir.configure(text=f"📁 Dossier local : {os.path.basename(ch) or ch}")

    # ================================================================
    # Navigation & Cache Simple
    # ================================================================
    def _get_cache_key(self, path: str) -> str:
        if not self.current_host_info:
            return path
        return f"{self.current_host_info[0]}:{self.current_host_info[1]}:{path}"

    def _open_manual_dialog(self, default_ip="", default_port=21):
        win = ctk.CTkToplevel(self)
        win.title("Connexion FTP / SFTP")
        win.geometry("380x330")
        win.resizable(False, False)
        win.grab_set()

        ctk.CTkLabel(win, text="Connexion au serveur", font=ctk.CTkFont(size=15, weight="bold")).pack(pady=10)
        f = ctk.CTkFrame(win, fg_color="transparent")
        f.pack(padx=20, fill="x")

        ctk.CTkLabel(f, text="Protocole :").grid(row=0, column=0, sticky="w", pady=4)
        proto_menu = ctk.CTkOptionMenu(f, values=["FTP", "SFTP", "FTPS"])
        proto_menu.grid(row=0, column=1, pady=4)

        ctk.CTkLabel(f, text="IP / Hôte :").grid(row=1, column=0, sticky="w", pady=4)
        ip_e = ctk.CTkEntry(f, width=180)
        ip_e.insert(0, default_ip or "192.168.1.")
        ip_e.grid(row=1, column=1, pady=4)

        ctk.CTkLabel(f, text="Port :").grid(row=2, column=0, sticky="w", pady=4)
        pt_e = ctk.CTkEntry(f, width=180)
        pt_e.insert(0, str(default_port))
        pt_e.grid(row=2, column=1, pady=4)

        ctk.CTkLabel(f, text="Utilisateur :").grid(row=3, column=0, sticky="w", pady=4)
        usr_e = ctk.CTkEntry(f, width=180, placeholder_text="(Vide = anonymous)")
        usr_e.grid(row=3, column=1, pady=4)

        ctk.CTkLabel(f, text="Mot de passe :").grid(row=4, column=0, sticky="w", pady=4)
        pwd_e = ctk.CTkEntry(f, width=180, show="*")
        pwd_e.grid(row=4, column=1, pady=4)

        def _do_connect():
            ip = ip_e.get().strip()
            port = int(pt_e.get().strip() or "21")
            user = usr_e.get().strip() or None
            pwd = pwd_e.get().strip() or None
            proto = proto_menu.get()
            win.destroy()
            self._establish_connection(ip, port, proto, user, pwd)

        ctk.CTkButton(win, text="Se Connecter", command=_do_connect).pack(pady=14)

    def _establish_connection(self, host: str, port: int, proto: str, user=None, pwd=None):
        self.spinner.start()
        self.status_bar.configure(text=f"Connexion à {host}:{port}...")

        def worker():
            try:
                if proto == "SFTP":
                    sess = SFTPSession(host, port, user, pwd)
                elif proto == "FTPS":
                    sess = FTPSession(host, port, user, pwd, use_tls=True)
                else:
                    sess = FTPSession(host, port, user, pwd, use_tls=False)

                sess.connect()
                self.current_session = sess
                self.current_host_info = (host, port, proto)
                self.history.clear()
                self.forward_history.clear()
                self.folder_cache.clear()
                self.after(0, lambda: self._load_folder("/", push_history=True))
            except Exception as e:
                self.after(0, lambda err=e: self._handle_auth_failure(host, port, proto, str(err)))
            finally:
                self.after(0, self.spinner.stop)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_auth_failure(self, host, port, proto, err_msg):
        self.status_bar.configure(text="Échec de connexion.")
        ans = messagebox.askyesno(
            "Authentification requise",
            f"La connexion a échoué sur {host}:{port} ({proto}) :\n{err_msg}\n\n"
            "Voulez-vous saisir vos identifiants manuellement ?"
        )
        if ans:
            self._open_manual_dialog(host, port)

    def _load_folder(self, path: str, push_history: bool = True, force_network: bool = False):
        if not self.current_session:
            return

        if push_history and self.current_path != path:
            self.history.append(self.current_path)
            self.forward_history.clear()

        self.current_path = path
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, path)

        cache_key = self._get_cache_key(path)

        if not force_network and cache_key in self.folder_cache:
            self._on_folder_data_ready(self.folder_cache[cache_key], from_cache=True)
            return

        self.spinner.start()
        self.status_bar.configure(text=f"Chargement de {path}...")

        def worker():
            try:
                entries = self.current_session.list_dir(path)
                self.folder_cache[cache_key] = entries
                self.after(0, lambda: self._on_folder_data_ready(entries, from_cache=False))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Erreur", str(e)))
            finally:
                self.after(0, self.spinner.stop)

        threading.Thread(target=worker, daemon=True).start()

    # ================================================================
    # Rendu Instantané & Cases à Cocher
    # ================================================================
    def _on_folder_data_ready(self, entries: List[RemoteEntry], from_cache: bool = False):
        self.all_entries = entries
        self.filtered_entries = list(entries)
        self.selected_entries.clear()
        self.chk_select_all.deselect()
        self._update_nav_buttons()

        self._render_files_directly()

        self.files_scroll._parent_canvas.yview_moveto(0.0)

        txt = f"{len(entries)} élément(s) dans {self.current_path}"
        if from_cache:
            txt += " [Cache]"
        self.status_bar.configure(text=txt)

    def _render_files_directly(self):
        if self.items_container:
            self.items_container.destroy()

        self.item_cards.clear()
        self.item_checkboxes.clear()

        self.items_container = ctk.CTkFrame(self.files_scroll, fg_color="transparent")
        self.items_container.pack(fill="both", expand=True, padx=4, pady=4)

        if not self.filtered_entries:
            empty_box = ctk.CTkFrame(self.items_container, fg_color="transparent")
            empty_box.pack(fill="both", expand=True, pady=100)

            ctk.CTkLabel(empty_box, text="📂", font=ctk.CTkFont(size=44)).pack(pady=(0, 8))
            ctk.CTkLabel(
                empty_box, text="Ce dossier est vide",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color=("#0f172a", "#f8fafc")
            ).pack()
            ctk.CTkLabel(
                empty_box, text="Glissez-déposez des fichiers pour téléverser",
                font=ctk.CTkFont(size=11),
                text_color=("#64748b", "#94a3b8")
            ).pack(pady=(4, 0))
            return

        self.current_grid_cols = self._compute_grid_cols()

        if self.view_mode == "grid":
            self._render_grid_view()
        else:
            self._render_list_view()

        # Met à jour la région de scroll et attache la molette à TOUS les éléments
        self.update_idletasks()
        self.files_scroll._parent_canvas.configure(scrollregion=self.files_scroll._parent_canvas.bbox("all"))
        self._bind_mousewheel_recursive(self.items_container)

    def _compute_grid_cols(self) -> int:
        w = self.files_scroll.winfo_width()
        if w <= 1:
            w = max(self.winfo_width() - 320, 960)
        return max(3, (w - 20) // (CARD_WIDTH + 8))

    def _on_container_resized(self, event):
        if self.view_mode != "grid" or not self.item_cards:
            return
        new_cols = self._compute_grid_cols()
        if new_cols != self.current_grid_cols and new_cols > 0:
            self.current_grid_cols = new_cols
            cols = self.current_grid_cols

            for i in range(cols):
                self.items_container.grid_columnconfigure(i, weight=0, minsize=CARD_WIDTH + 8)

            for idx, (entry, card) in enumerate(self.item_cards.items()):
                r = idx // cols
                c = idx % cols
                card.grid(row=r, column=c, padx=4, pady=4, sticky="nw")

            self.update_idletasks()
            self.files_scroll._parent_canvas.configure(scrollregion=self.files_scroll._parent_canvas.bbox("all"))

    def _render_grid_view(self):
        cols = self.current_grid_cols
        for i in range(cols):
            self.items_container.grid_columnconfigure(i, weight=0, minsize=CARD_WIDTH + 8)

        for idx, entry in enumerate(self.filtered_entries):
            r = idx // cols
            c = idx % cols

            icon = "📁" if entry.is_dir else FILE_ICONS.get(entry.name.split(".")[-1].lower(), "📄")
            short_name = entry.name if len(entry.name) <= 13 else entry.name[:10] + "..."
            sub = "Dossier" if entry.is_dir else self._format_size(entry.size)

            card = ctk.CTkFrame(
                self.items_container,
                corner_radius=8,
                border_width=1,
                width=CARD_WIDTH,
                height=CARD_HEIGHT,
                fg_color=("#ffffff", "#1e293b"),
                border_color=("#e2e8f0", "#334155")
            )
            card.pack_propagate(False)
            card.grid(row=r, column=c, padx=4, pady=4, sticky="nw")

            # Barre supérieure de la carte avec la case à cocher
            top_bar = ctk.CTkFrame(card, fg_color="transparent")
            top_bar.pack(fill="x", padx=4, pady=(4, 0))

            chk = ctk.CTkCheckBox(
                top_bar, text="", width=16, height=16, checkbox_width=16, checkbox_height=16,
                command=lambda e=entry: self._on_checkbox_toggled(e)
            )
            chk.pack(side="left")

            lbl_i = ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=24))
            lbl_i.pack(pady=(2, 2))

            lbl_n = ctk.CTkLabel(
                card, text=short_name, font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#0f172a", "#f8fafc")
            )
            lbl_n.pack(padx=2)

            lbl_s = ctk.CTkLabel(
                card, text=sub, font=ctk.CTkFont(size=9),
                text_color=("#64748b", "#94a3b8")
            )
            lbl_s.pack(pady=(0, 2))

            self.item_cards[entry] = card
            self.item_checkboxes[entry] = chk

            # Double-clic pour ouvrir / Clic droit menu contextuel
            for w in (card, lbl_i, lbl_n, lbl_s):
                w.bind("<Double-Button-1>", lambda event, e=entry: self._on_entry_double_click(e))
                w.bind("<Button-3>", lambda event, e=entry: self.context_menu.show(e, event))

            card.bind("<Enter>", lambda e, c=card, ent=entry: self._on_card_hover(c, ent, True))
            card.bind("<Leave>", lambda e, c=card, ent=entry: self._on_card_hover(c, ent, False))

    def _render_list_view(self):
        for entry in self.filtered_entries:
            row = ctk.CTkFrame(
                self.items_container, corner_radius=6, border_width=1, height=36,
                fg_color=("#ffffff", "#1e293b"), border_color=("#e2e8f0", "#334155")
            )
            row.pack_propagate(False)
            row.pack(fill="x", pady=2, padx=4)
            row.grid_columnconfigure(2, weight=1)

            chk = ctk.CTkCheckBox(
                row, text="", width=18, height=18, checkbox_width=16, checkbox_height=16,
                command=lambda e=entry: self._on_checkbox_toggled(e)
            )
            chk.grid(row=0, column=0, padx=(8, 4), pady=4)

            icon = "📁" if entry.is_dir else FILE_ICONS.get(entry.name.split(".")[-1].lower(), "📄")
            lbl_i = ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=18), width=30)
            lbl_i.grid(row=0, column=1, padx=4, pady=4)

            lbl_n = ctk.CTkLabel(
                row, text=entry.name, anchor="w", font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("#0f172a", "#f8fafc")
            )
            lbl_n.grid(row=0, column=2, sticky="w", padx=6)

            size_txt = "--" if entry.is_dir else self._format_size(entry.size)
            lbl_s = ctk.CTkLabel(
                row, text=size_txt, width=90, anchor="e",
                font=ctk.CTkFont(size=11), text_color=("#64748b", "#94a3b8")
            )
            lbl_s.grid(row=0, column=3, padx=10)

            self.item_cards[entry] = row
            self.item_checkboxes[entry] = chk

            for w in (row, lbl_i, lbl_n, lbl_s):
                w.bind("<Double-Button-1>", lambda event, e=entry: self._on_entry_double_click(e))
                w.bind("<Button-3>", lambda event, e=entry: self.context_menu.show(e, event))

            row.bind("<Enter>", lambda e, r=row, ent=entry: self._on_card_hover(r, ent, True))
            row.bind("<Leave>", lambda e, r=row, ent=entry: self._on_card_hover(r, ent, False))

    # ================================================================
    # Sélection via Cases à Cocher
    # ================================================================
    def _on_checkbox_toggled(self, entry: RemoteEntry):
        chk = self.item_checkboxes.get(entry)
        if not chk:
            return

        if chk.get() == 1:
            self.selected_entries.add(entry)
        else:
            self.selected_entries.discard(entry)

        self._refresh_card_style(entry)
        self._update_selection_label()

    def _on_select_all_checked(self):
        is_checked = (self.chk_select_all.get() == 1)
        self._select_all_toggle(is_checked)

    def _select_all_toggle(self, select: bool):
        if select:
            self.selected_entries = set(self.filtered_entries)
            self.chk_select_all.select()
        else:
            self.selected_entries.clear()
            self.chk_select_all.deselect()

        for ent, chk in self.item_checkboxes.items():
            if select:
                chk.select()
            else:
                chk.deselect()
            self._refresh_card_style(ent)

        self._update_selection_label()

    def _on_card_hover(self, widget: ctk.CTkFrame, entry: RemoteEntry, is_hover: bool):
        if entry not in self.selected_entries:
            if is_hover:
                widget.configure(fg_color=("#f1f5f9", "#2e3846"), border_color=("#3b82f6", "#3b82f6"))
            else:
                widget.configure(fg_color=("#ffffff", "#1e293b"), border_color=("#e2e8f0", "#334155"))

    def _refresh_card_style(self, entry: RemoteEntry):
        card = self.item_cards.get(entry)
        if not card:
            return
        if entry in self.selected_entries:
            card.configure(fg_color=("#dbeafe", "#1e3a8a"), border_color=("#3b82f6", "#60a5fa"))
        else:
            card.configure(fg_color=("#ffffff", "#1e293b"), border_color=("#e2e8f0", "#334155"))

    def _refresh_all_visuals(self):
        for ent in self.item_cards:
            self._refresh_card_style(ent)

    def _update_selection_label(self):
        n = len(self.selected_entries)
        self.selection_label.configure(text=f"{n} élément(s) coché(s)")
        has_files = any(not e.is_dir for e in self.selected_entries)
        self.btn_download.configure(state="normal" if has_files else "disabled")

    # ================================================================
    # Double-Clic : Ouverture Système
    # ================================================================
    def _on_entry_double_click(self, entry: RemoteEntry):
        if entry.is_dir:
            new_p = sanitize_remote_path(self.current_path, entry.name)
            self._load_folder(new_p, push_history=True)
        else:
            self._open_system_default(entry)

    def _open_system_default(self, entry: RemoteEntry):
        tmp = os.path.join(tempfile.gettempdir(), entry.name)
        rpath = sanitize_remote_path(self.current_path, entry.name)
        self.status_bar.configure(text=f"Ouverture de '{entry.name}'...")

        def worker():
            try:
                self.current_session.download_file(rpath, tmp)
                self.after(0, lambda: self.status_bar.configure(text=f"'{entry.name}' ouvert."))

                if sys.platform.startswith("win"):
                    os.startfile(tmp)
                elif sys.platform.startswith("darwin"):
                    subprocess.Popen(["open", tmp])
                else:
                    subprocess.Popen(["xdg-open", tmp])
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier :\n{e}"))

        threading.Thread(target=worker, daemon=True).start()

    # ================================================================
    # Recherche
    # ================================================================
    def _on_search_key_release(self, event):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(150, self._apply_search_filter)

    def _apply_search_filter(self):
        q = self.search_entry.get().lower().strip()
        if not q:
            self.filtered_entries = list(self.all_entries)
        else:
            self.filtered_entries = [e for e in self.all_entries if q in e.name.lower()]
        self._render_files_directly()

    # ================================================================
    # Transferts
    # ================================================================
    def _download_selected_to_target(self):
        targets = [e for e in self.selected_entries if not e.is_dir]
        if not targets or not self.current_session:
            return

        for ent in targets:
            rpath = sanitize_remote_path(self.current_path, ent.name)
            loc = os.path.join(self.local_download_dir, ent.name)
            self.transfers.add_download(self.current_session, rpath, loc, ent.name, ent.size)

        messagebox.showinfo("Transfert", f"{len(targets)} fichier(s) ajoutés à la file d'attente vers :\n{self.local_download_dir}")

    def _on_upload_pick(self):
        if not self.current_session:
            return
        files = filedialog.askopenfilenames(title="Sélectionner les fichiers à envoyer")
        if files:
            self._start_upload_job(list(files))

    def _start_upload_job(self, paths: List[str]):
        cache_key = self._get_cache_key(self.current_path)
        self.folder_cache.pop(cache_key, None)

        for lpath in paths:
            fname = os.path.basename(lpath)
            rpath = sanitize_remote_path(self.current_path, fname)
            sz = os.path.getsize(lpath)
            self.transfers.add_upload(self.current_session, lpath, rpath, fname, sz)

    def _on_context_action(self, action: str, entry: RemoteEntry):
        if action in ("preview", "system_open"):
            self._open_system_default(entry)
        elif action == "download":
            rpath = sanitize_remote_path(self.current_path, entry.name)
            loc = os.path.join(self.local_download_dir, entry.name)
            self.transfers.add_download(self.current_session, rpath, loc, entry.name, entry.size)
        elif action == "s2s":
            self._server_to_server_prompt(entry)
        elif action == "rename":
            self._rename_entry(entry)
        elif action == "delete":
            self._delete_entry(entry)

    def _server_to_server_prompt(self, entry: RemoteEntry):
        ip = simpledialog.askstring("Transfert inter-serveur", "IP / Hôte du serveur distant cible :")
        if not ip:
            return
        dst_sess = FTPSession(ip.strip(), 21)
        try:
            dst_sess.connect()
            src_p = sanitize_remote_path(self.current_path, entry.name)
            self.transfers.add_server_to_server(self.current_session, src_p, dst_sess, f"/{entry.name}", entry.name, entry.size)
            messagebox.showinfo("Transfert", f"Transfert direct vers {ip} lancé.")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def _on_mkdir(self):
        name = simpledialog.askstring("Nouveau dossier", "Nom :", parent=self)
        if name:
            rpath = sanitize_remote_path(self.current_path, name.strip())
            cache_key = self._get_cache_key(self.current_path)
            self.folder_cache.pop(cache_key, None)
            threading.Thread(
                target=lambda: (self.current_session.create_dir(rpath), self.after(0, lambda: self._load_folder(self.current_path, push_history=False, force_network=True))),
                daemon=True
            ).start()

    def _rename_selected(self):
        if len(self.selected_entries) == 1:
            self._rename_entry(list(self.selected_entries)[0])

    def _rename_entry(self, entry: RemoteEntry):
        new_name = simpledialog.askstring("Renommer", "Nouveau nom :", initialvalue=entry.name, parent=self)
        if new_name and new_name != entry.name:
            old_p = sanitize_remote_path(self.current_path, entry.name)
            new_p = sanitize_remote_path(self.current_path, new_name.strip())
            cache_key = self._get_cache_key(self.current_path)
            self.folder_cache.pop(cache_key, None)
            threading.Thread(
                target=lambda: (self.current_session.rename(old_p, new_p), self.after(0, lambda: self._load_folder(self.current_path, push_history=False, force_network=True))),
                daemon=True
            ).start()

    def _delete_selected(self):
        for e in list(self.selected_entries):
            self._delete_entry(e)

    def _delete_entry(self, entry: RemoteEntry):
        if messagebox.askyesno("Suppression", f"Supprimer '{entry.name}' ?"):
            rpath = sanitize_remote_path(self.current_path, entry.name)
            cache_key = self._get_cache_key(self.current_path)
            self.folder_cache.pop(cache_key, None)
            def worker():
                try:
                    if entry.is_dir:
                        self.current_session.delete_dir_recursive(rpath)
                    else:
                        self.current_session.delete_file(rpath)
                    self.after(0, lambda: self._load_folder(self.current_path, push_history=False, force_network=True))
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror("Erreur", str(e)))
            threading.Thread(target=worker, daemon=True).start()

    def _update_transfer_status(self):
        count, spd = self.transfers.get_summary()
        self.btn_dashboard.configure(text=f"📊 Transferts ({count})")
        if count > 0:
            self.status_bar.configure(text=f"🚀 {count} transfert(s) — {spd / (1024*1024):.2f} Mo/s")
        else:
            self.status_bar.configure(text="Prêt.")

    # ================================================================
    # Scan Réseau
    # ================================================================
    def _start_scan(self):
        ports = scanner.parse_ports_input(self.ports_entry.get())
        for w in self.hosts_scroll.winfo_children():
            w.destroy()

        self.scan_progress.set(0)
        self.scan_btn.configure(state="disabled", text="Scan...")
        self.spinner.start()

        def worker():
            def prog(d, t):
                self.after(0, lambda: self.scan_progress.set(d / t if t else 0))
            hosts = scanner.scan_network(ports=ports, progress_callback=prog)
            self.after(0, lambda: self._on_scan_finished(hosts))

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_finished(self, hosts: List[scanner.DetectedServer]):
        self.spinner.stop()
        self.scan_btn.configure(state="normal", text="Scanner")
        self.scan_progress.set(1.0)

        if not hosts:
            self.status_bar.configure(text="Aucun serveur détecté.")
            ctk.CTkLabel(
                self.hosts_scroll, text="Aucun serveur trouvé.",
                text_color=("#64748b", "#94a3b8")
            ).pack(pady=8)
            return

        self.status_bar.configure(text=f"{len(hosts)} serveur(s) détecté(s).")
        for h in hosts:
            badge = "🟢" if h.is_anonymous else ("🛡️" if h.protocol == "SFTP" else "🔒")
            btn = ctk.CTkButton(
                self.hosts_scroll,
                text=f"🖥 {badge} {h.protocol} {h.ip}:{h.port}\n   {h.banner or 'Prêt'}",
                anchor="w",
                fg_color=("#ffffff", "#1e293b"),
                hover_color=("#f1f5f9", "#334155"),
                text_color=("#0f172a", "#f8fafc"),
                border_color=("#cbd5e1", "#334155"),
                border_width=1,
                corner_radius=8,
                command=lambda s=h: self._establish_connection(s.ip, s.port, s.protocol)
            )
            btn.pack(fill="x", pady=2, padx=2)

    # ================================================================
    # Navigation
    # ================================================================
    def _nav_back(self):
        if self.history:
            self.forward_history.append(self.current_path)
            self._load_folder(self.history.pop(), push_history=False)

    def _nav_fwd(self):
        if self.forward_history:
            self.history.append(self.current_path)
            self._load_folder(self.forward_history.pop(), push_history=False)

    def _nav_up(self):
        if self.current_path not in ("/", ""):
            parent = self.current_path.rstrip("/").rsplit("/", 1)[0] or "/"
            self._load_folder(parent, push_history=True)

    def _on_path_entered(self):
        t = self.path_entry.get().strip() or "/"
        self._load_folder(t, push_history=True)

    def _refresh_current_folder(self, force_network: bool = True):
        self._load_folder(self.current_path, push_history=False, force_network=force_network)

    def _update_nav_buttons(self):
        self.btn_back.configure(state="normal" if self.history else "disabled")
        self.btn_fwd.configure(state="normal" if self.forward_history else "disabled")
        self.btn_up.configure(state="normal" if self.current_path not in ("/", "") else "disabled")
        self.btn_mkdir.configure(state="normal" if self.current_session else "disabled")
        self.btn_upload.configure(state="normal" if self.current_session else "disabled")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        s = float(size_bytes)
        for u in ("o", "Ko", "Mo", "Go"):
            if s < 1024:
                return f"{s:.0f} {u}" if u == "o" else f"{s:.1f} {u}"
            s /= 1024
        return f"{s:.1f} To"


if __name__ == "__main__":
    app = FTPScannerApp()
    app.mainloop()