"""
ui_components.py
================
Composants d'interface : Fil d'ariane (Breadcrumbs), Menu Clic Droit,
Mini-barre escamotable de transfert et Grand tableau de bord complet.
"""

import os
import tkinter as tk
from typing import Callable, List

import customtkinter as ctk
from transfer_manager import TransferManager


class BreadcrumbsBar(ctk.CTkFrame):
    """Barre de navigation interactive sous forme de boutons segmentés."""

    def __init__(self, master, on_navigate: Callable, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_navigate = on_navigate

    def set_path(self, path: str):
        for w in self.winfo_children():
            w.destroy()

        segments = [s for s in path.split("/") if s]
        btn_root = ctk.CTkButton(
            self, text="🏠 Racine", width=70, height=26, fg_color="transparent",
            border_width=1, command=lambda: self.on_navigate("/")
        )
        btn_root.pack(side="left", padx=2)

        curr = ""
        for seg in segments:
            curr += f"/{seg}"
            ctk.CTkLabel(self, text=">", text_color="gray50").pack(side="left", padx=2)
            btn = ctk.CTkButton(
                self, text=seg, height=26, fg_color="transparent",
                border_width=1, command=lambda p=curr: self.on_navigate(p)
            )
            btn.pack(side="left", padx=2)


class ContextMenu:
    """Menu surgissant au clic droit (Style GNOME)."""

    def __init__(self, root, on_action: Callable):
        self.root = root
        self.on_action = on_action
        self.menu = tk.Menu(root, tearoff=0)

    def show(self, entry, event):
        self.menu.delete(0, "end")
        self.menu.add_command(label=f"👁 Ouvrir / Prévisualiser", command=lambda: self.on_action("preview", entry))
        self.menu.add_command(label="🚀 Ouvrir avec l'application système", command=lambda: self.on_action("system_open", entry))
        self.menu.add_separator()
        self.menu.add_command(label="⬇ Télécharger", command=lambda: self.on_action("download", entry))
        self.menu.add_command(label="🔄 Transférer vers un autre serveur...", command=lambda: self.on_action("s2s", entry))
        self.menu.add_separator()
        self.menu.add_command(label="✏️ Renommer (F2)", command=lambda: self.on_action("rename", entry))
        self.menu.add_command(label="🗑️ Supprimer (Suppr)", command=lambda: self.on_action("delete", entry))

        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()


class TransferMiniBar(ctk.CTkFrame):
    """Mini-tiroir escamotable en bas d'écran avec débit Mo/s et ETA."""

    def __init__(self, master, on_expand: Callable, **kwargs):
        super().__init__(master, corner_radius=8, **kwargs)
        self.on_expand = on_expand

        self.lbl_status = ctk.CTkLabel(self, text="Aucun transfert actif.", font=ctk.CTkFont(size=12))
        self.lbl_status.pack(side="left", padx=12, pady=4)

        self.btn_expand = ctk.CTkButton(self, text="📊 Tableau de bord", width=120, height=24, command=self.on_expand)
        self.btn_expand.pack(side="right", padx=10, pady=4)

    def update_info(self, count: int, speed: float):
        if count > 0:
            spd_mb = speed / (1024 * 1024)
            self.lbl_status.configure(text=f"🚀 {count} transfert(s) en cours — {spd_mb:.2f} Mo/s")
        else:
            self.lbl_status.configure(text="Prêt — Tous les transferts sont terminés.")


class TransferDashboardModal(ctk.CTkToplevel):
    """Grand tableau de bord plein écran de suivi et contrôle des transferts."""

    def __init__(self, master, manager: TransferManager):
        super().__init__(master)
        self.manager = manager
        self.title("Centre de Suivi des Transferts")
        self.geometry("820x460")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # En-tête
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        ctk.CTkLabel(head, text="Flux et Fichiers en cours", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="Nettoyer terminés", width=120, command=self._clear).pack(side="right")

        # Liste scrollable
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))

        self.after(500, self._refresh)

    def _refresh(self):
        if not self.winfo_exists():
            return

        for w in self.scroll.winfo_children():
            w.destroy()

        for t in self.manager.tasks:
            row = ctk.CTkFrame(self.scroll, corner_radius=6)
            row.pack(fill="x", pady=3, padx=4)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(row, text=t.name, width=180, anchor="w", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=8)

            pct = (t.transferred_bytes / t.total_bytes) if t.total_bytes else 0
            prog = ctk.CTkProgressBar(row, width=200)
            prog.set(pct)
            prog.grid(row=0, column=1, padx=8)

            info = f"{t.speed / (1024*1024):.1f} Mo/s | {int(pct*100)}%"
            ctk.CTkLabel(row, text=info, width=110).grid(row=0, column=2, padx=8)

            ctk.CTkLabel(row, text=t.status.upper(), width=80).grid(row=0, column=3, padx=4)

            btn_cancel = ctk.CTkButton(
                row, text="✕", width=28, height=24, fg_color="#ef4444",
                command=lambda task_id=t.id: self.manager.cancel_task(task_id)
            )
            btn_cancel.grid(row=0, column=4, padx=6)

        self.after(1000, self._refresh)

    def _clear(self):
        self.manager.clear_finished()
        self._refresh()