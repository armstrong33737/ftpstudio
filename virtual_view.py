"""
virtual_view.py
===============
Explorateur de fichiers à chargement infini (Infinite Scroll / Progressive Batching).
Charge les fichiers par lots (50 par 50). Une fois chargé, un élément reste
définitivement affiché sans recalculs destructeurs (aucun freeze au scroll).
"""

from typing import Callable, List, Optional, Set
import customtkinter as ctk
from remote_engine import RemoteEntry

# Palette de couleurs modernes (Thème GNOME Slate)
THEME_COLORS = {
    "dark": {
        "bg_container": "#111827",
        "card_bg": "#1e293b",
        "card_border": "#334155",
        "hover_bg": "#334155",
        "hover_border": "#3b82f6",
        "selected_bg": "#1e3a8a",
        "selected_border": "#60a5fa",
        "text_primary": "#f8fafc",
        "text_secondary": "#94a3b8",
        "folder_icon": "#fbbf24",
    },
    "light": {
        "bg_container": "#f8fafc",
        "card_bg": "#ffffff",
        "card_border": "#e2e8f0",
        "hover_bg": "#f1f5f9",
        "hover_border": "#3b82f6",
        "selected_bg": "#dbeafe",
        "selected_border": "#2563eb",
        "text_primary": "#0f172a",
        "text_secondary": "#64748b",
        "folder_icon": "#f59e0b",
    }
}

FILE_ICONS = {
    "pdf": "📕", "png": "🖼", "jpg": "🖼", "jpeg": "🖼", "webp": "🖼", "gif": "🖼",
    "mp4": "🎬", "mkv": "🎬", "avi": "🎬", "mp3": "🎵", "flac": "🎵", "wav": "🎵",
    "zip": "📦", "tar": "📦", "gz": "📦", "7z": "📦", "rar": "📦",
    "py": "🐍", "json": "📜", "txt": "📄", "md": "📝", "csv": "📊", "html": "🌐"
}


class VirtualExplorerView(ctk.CTkFrame):
    """Explorateur avec défilement fluide et persistant (Infinite Feed)."""

    def __init__(self, master, on_select: Callable, on_open: Callable, on_context_menu: Callable, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_select = on_select
        self.on_open = on_open
        self.on_context_menu = on_context_menu

        self.entries: List[RemoteEntry] = []
        self.filtered_entries: List[RemoteEntry] = []
        self.selected_entries: Set[RemoteEntry] = set()

        self.view_mode = "grid"      # "grid" ou "list"
        self.theme_mode = "dark"
        self.batch_size = 50          # Nombre d'éléments chargés par lot
        self.loaded_count = 0        # Nombre d'éléments actuellement affichés
        self.entry_cards = {}        # {entry: widget_frame}

        self._build_ui()

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Conteneur scrollable natif de CustomTkinter (très stable)
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=THEME_COLORS[self.theme_mode]["bg_container"],
            corner_radius=10
        )
        self.scroll_frame.grid(row=0, column=0, sticky="nsew")

        # Conteneur interne pour la grille ou la liste
        self.items_container = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        self.items_container.pack(fill="both", expand=True, padx=4, pady=4)

        # Bouton indicateur "Charger plus" en bas de page
        self.btn_load_more = ctk.CTkButton(
            self.scroll_frame,
            text="⬇ Charger les fichiers suivants",
            height=30,
            fg_color="transparent",
            border_width=1,
            command=self._load_next_batch
        )

        # Détection du bas de scroll pour charger automatiquement la suite
        self.scroll_frame._parent_canvas.bind("<Configure>", lambda e: self._check_scroll_load())
        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.scroll_frame._parent_canvas.bind(seq, self._on_scroll_activity, add="+")

    def _on_scroll_activity(self, event):
        self.after(50, self._check_scroll_load)

    def _check_scroll_load(self):
        """Si l'utilisateur arrive à 80% du bas, charge le lot suivant automatiquement."""
        if self.loaded_count >= len(self.filtered_entries):
            return
        yview = self.scroll_frame._parent_canvas.yview()
        if len(yview) == 2 and yview[1] >= 0.78:
            self._load_next_batch()

    def set_entries(self, entries: List[RemoteEntry]):
        """Initialise un nouveau dossier et charge le premier lot."""
        self.entries = entries
        self.filtered_entries = list(entries)
        self.selected_entries.clear()
        self._reset_and_render_initial()

    def filter_text(self, text: str):
        """Filtre instantané en mémoire sans jamais planter."""
        q = text.lower().strip()
        if not q:
            self.filtered_entries = list(self.entries)
        else:
            self.filtered_entries = [e for e in self.entries if q in e.name.lower()]
        self._reset_and_render_initial()

    def _reset_and_render_initial(self):
        for w in self.items_container.winfo_children():
            w.destroy()
        self.entry_cards.clear()
        self.loaded_count = 0
        self.btn_load_more.pack_forget()

        if not self.filtered_entries:
            ctk.CTkLabel(
                self.items_container,
                text="Dossier vide ou aucun fichier correspondant.",
                font=ctk.CTkFont(size=13),
                text_color=THEME_COLORS[self.theme_mode]["text_secondary"]
            ).pack(pady=40)
            return

        self._load_next_batch()

    def _load_next_batch(self):
        """Ajoute le lot suivant au DOM. Les éléments précédents restent en place !"""
        total = len(self.filtered_entries)
        if self.loaded_count >= total:
            self.btn_load_more.pack_forget()
            return

        start = self.loaded_count
        end = min(total, start + self.batch_size)
        batch = self.filtered_entries[start:end]

        if self.view_mode == "grid":
            self._render_grid_batch(batch, start)
        else:
            self._render_list_batch(batch)

        self.loaded_count = end

        # Affiche le bouton "Charger plus" s'il reste des éléments
        if self.loaded_count < total:
            remaining = total - self.loaded_count
            self.btn_load_more.configure(text=f"⬇ Charger la suite ({remaining} restant(s))...")
            self.btn_load_more.pack(pady=12, fill="x", padx=40)
        else:
            self.btn_load_more.pack_forget()

    def _render_grid_batch(self, batch: List[RemoteEntry], start_idx: int):
        cols = 5
        for i in range(cols):
            self.items_container.grid_columnconfigure(i, weight=1, uniform="card_col")

        colors = THEME_COLORS[self.theme_mode]

        for i, entry in enumerate(batch):
            idx = start_idx + i
            row = idx // cols
            col = idx % cols

            card = ctk.CTkFrame(
                self.items_container,
                corner_radius=10,
                border_width=1,
                fg_color=colors["card_bg"],
                border_color=colors["card_border"],
                height=110
            )
            card.pack_propagate(False)
            card.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")

            icon_char = "📁" if entry.is_dir else self._get_icon(entry.name)
            lbl_icon = ctk.CTkLabel(card, text=icon_char, font=ctk.CTkFont(size=28))
            lbl_icon.pack(pady=(12, 4))

            short_name = entry.name if len(entry.name) <= 17 else entry.name[:14] + "..."
            lbl_name = ctk.CTkLabel(card, text=short_name, font=ctk.CTkFont(size=12, weight="bold"))
            lbl_name.pack(padx=4)

            sub_txt = "Dossier" if entry.is_dir else self._format_size(entry.size)
            lbl_sub = ctk.CTkLabel(card, text=sub_txt, font=ctk.CTkFont(size=10), text_color=colors["text_secondary"])
            lbl_sub.pack(pady=(0, 6))

            self.entry_cards[entry] = card

            # Bindings complets
            for w in (card, lbl_icon, lbl_name, lbl_sub):
                w.bind("<Button-1>", lambda e, ent=entry: self._on_entry_click(ent, e))
                w.bind("<Double-Button-1>", lambda e, ent=entry: self._on_entry_double_click(ent))
                w.bind("<Button-3>", lambda e, ent=entry: self.on_context_menu(ent, e))
                w.bind("<Enter>", lambda e, c=card, ent=entry: self._on_hover(c, ent, True))
                w.bind("<Leave>", lambda e, c=card, ent=entry: self._on_hover(c, ent, False))

    def _render_list_batch(self, batch: List[RemoteEntry]):
        colors = THEME_COLORS[self.theme_mode]

        for entry in batch:
            row = ctk.CTkFrame(
                self.items_container,
                corner_radius=8,
                border_width=1,
                fg_color=colors["card_bg"],
                border_color=colors["card_border"],
                height=38
            )
            row.pack_propagate(False)
            row.pack(fill="x", pady=2, padx=4)
            row.grid_columnconfigure(1, weight=1)

            icon_char = "📁" if entry.is_dir else self._get_icon(entry.name)
            lbl_i = ctk.CTkLabel(row, text=icon_char, font=ctk.CTkFont(size=18), width=36)
            lbl_i.grid(row=0, column=0, padx=6, pady=4)

            lbl_n = ctk.CTkLabel(row, text=entry.name, anchor="w", font=ctk.CTkFont(size=12, weight="bold"))
            lbl_n.grid(row=0, column=1, sticky="w", padx=6)

            sub_txt = "--" if entry.is_dir else self._format_size(entry.size)
            lbl_s = ctk.CTkLabel(row, text=sub_txt, width=90, anchor="e", font=ctk.CTkFont(size=11), text_color=colors["text_secondary"])
            lbl_s.grid(row=0, column=2, padx=12)

            self.entry_cards[entry] = row

            for w in (row, lbl_i, lbl_n, lbl_s):
                w.bind("<Button-1>", lambda e, ent=entry: self._on_entry_click(ent, e))
                w.bind("<Double-Button-1>", lambda e, ent=entry: self._on_entry_double_click(ent))
                w.bind("<Button-3>", lambda e, ent=entry: self.on_context_menu(ent, e))
                w.bind("<Enter>", lambda e, c=row, ent=entry: self._on_hover(c, ent, True))
                w.bind("<Leave>", lambda e, c=row, ent=entry: self._on_hover(c, ent, False))

    def _on_hover(self, card_widget, entry: RemoteEntry, is_hover: bool):
        colors = THEME_COLORS[self.theme_mode]
        is_sel = entry in self.selected_entries
        if is_sel:
            card_widget.configure(fg_color=colors["selected_bg"], border_color=colors["selected_border"])
        elif is_hover:
            card_widget.configure(fg_color=colors["hover_bg"], border_color=colors["hover_border"])
        else:
            card_widget.configure(fg_color=colors["card_bg"], border_color=colors["card_border"])

    def _on_entry_click(self, entry: RemoteEntry, event):
        ctrl = (event.state & 0x0004) or (event.state & 0x0008)
        if ctrl:
            if entry in self.selected_entries:
                self.selected_entries.remove(entry)
            else:
                self.selected_entries.add(entry)
        else:
            self.selected_entries = {entry}

        self._refresh_selection_styles()
        self.on_select(self.selected_entries)

    def _on_entry_double_click(self, entry: RemoteEntry):
        if entry:
            self.on_open(entry)

    def _refresh_selection_styles(self):
        colors = THEME_COLORS[self.theme_mode]
        for ent, card in self.entry_cards.items():
            if ent in self.selected_entries:
                card.configure(fg_color=colors["selected_bg"], border_color=colors["selected_border"])
            else:
                card.configure(fg_color=colors["card_bg"], border_color=colors["card_border"])

    def toggle_view(self, mode: str):
        self.view_mode = "grid" if "Grille" in mode else "list"
        self._reset_and_render_initial()

    def set_theme(self, mode: str):
        self.theme_mode = mode
        colors = THEME_COLORS[self.theme_mode]
        self.scroll_frame.configure(fg_color=colors["bg_container"])
        self._refresh_selection_styles()

    @staticmethod
    def _get_icon(name: str) -> str:
        ext = name.split(".")[-1].lower() if "." in name else ""
        return FILE_ICONS.get(ext, "📄")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        s = float(size_bytes)
        for u in ("o", "Ko", "Mo", "Go"):
            if s < 1024:
                return f"{s:.0f} {u}" if u == "o" else f"{s:.1f} {u}"
            s /= 1024
        return f"{s:.1f} To"