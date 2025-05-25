#!/usr/bin/env python3
"""
manage_realms.py – A Toplevel window for toggling realm selection in Servana GUI.

Opens as a child window (not a second root) when invoked from the cog button.
Persists enabled/disabled flags in a shelve under `.cache/realms_settings.db`.
Contains only a search bar and a realm list tree.
"""
import os
import shelve
import tkinter as tk
from tkinter import ttk

# Constants
script_dir = os.path.dirname(__file__)
cache_dir = os.path.join(script_dir, '.cache')
SETTINGS_DB = os.path.join(cache_dir, 'realms_settings.db')
REALMS_DB   = os.path.join(cache_dir, 'realms_cache.db')

class RealmManager(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Manage Realms")
        self.geometry("400x300")
        self.configure(bg='#2e2e2e')
        self.resizable(False, False)

        # Load realm data and settings
        with shelve.open(REALMS_DB) as db:
            self.realms = {int(rid): db[rid] for rid in db.keys()}
        with shelve.open(SETTINGS_DB) as db:
            self.settings = {int(rid): db.get(rid, True) for rid in self.realms.keys()}

        self.filtered = list(self.realms.keys())
        self._build_ui()

    def _build_ui(self):
        # Search bar
        search_frame = tk.Frame(self, bg='#2e2e2e', bd=0, highlightthickness=0)
        search_frame.pack(fill='x', padx=10, pady=10)
        tk.Label(search_frame, text='Search:', bg='#2e2e2e', fg='#ffffff').pack(side='left')
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side='left', fill='x', expand=True, padx=(5,0))
        self.search_var.trace_add('write', self._on_search)

        # Treeview style
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Dark.Treeview', background='#2e2e2e', fieldbackground='#2e2e2e', foreground='#ffffff')
        style.configure('Dark.Treeview.Heading', background='#1e1e1e', foreground='#ffffff')

        # Treeview of realms
        cols = ('Realm Name',)
        self.tree = ttk.Treeview(self, columns=cols, show='headings', height=12, style='Dark.Treeview')
        self.tree.heading('Realm Name', text='Realm Name')
        self.tree.column('Realm Name', anchor='w', width=380)
        self.tree.pack(padx=10, pady=(0,10), fill='both', expand=True)
        self.tree.tag_configure('enabled', background='#335533', foreground='#ffffff')
        self.tree.tag_configure('disabled', background='#553333', foreground='#ffffff')
        self.tree.bind('<Double-1>', self._on_toggle)

        # Initial population
        self._populate_tree()

    def _populate_tree(self):
        # Clear
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        # Insert
        for rid in self.filtered:
            data = self.realms[rid]
            name = data.get('name', '')
            enabled = self.settings.get(rid, True)
            tag = 'enabled' if enabled else 'disabled'
            self.tree.insert('', 'end', iid=str(rid), values=(name,), tags=(tag,))

    def _on_search(self, *args):
        q = self.search_var.get().lower()
        self.filtered = [rid for rid, d in self.realms.items() if q in d.get('name','').lower()]
        self._populate_tree()

    def _on_toggle(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        rid = int(item)
        new_state = not self.settings.get(rid, True)
        self.settings[rid] = new_state
        with shelve.open(SETTINGS_DB, writeback=True) as db:
            db[str(rid)] = new_state
        # Refresh tag only (no Enabled column)
        tag = 'enabled' if new_state else 'disabled'
        self.tree.item(item, tags=(tag,))

# End of file
