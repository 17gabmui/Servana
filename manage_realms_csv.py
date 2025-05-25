#!/usr/bin/env python3
import os
import csv
import shelve
import tkinter as tk
from tkinter import ttk, messagebox

CACHE_DIR   = os.path.join(os.path.dirname(__file__), ".cache")
REALMS_CSV  = os.path.join(CACHE_DIR, "realms.csv")
SETTINGS_DB = os.path.join(CACHE_DIR, "realms_settings.db")

def load_selected_realms():
    """
    Return {realm_id: realm_name} for realms with enabled=True in SETTINGS_DB.
    """
    realms = {}
    if os.path.isfile(REALMS_CSV):
        with open(REALMS_CSV, newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                if len(row) == 1 and ":" in row[0]:
                    rid, name = row[0].split(":", 1)
                else:
                    rid, name = row[0], row[1]
                try:
                    realms[int(rid)] = name.strip()
                except ValueError:
                    continue

    enabled = {}
    with shelve.open(SETTINGS_DB) as db:
        for rid, name in realms.items():
            if db.get(str(rid), True):
                enabled[rid] = name
    return enabled


class RealmManager(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Manage Realms")
        self.configure(bg="#2e2e2e")
        self.resizable(True, True)

        # Load all realms and their saved flags
        self.all_realms = {}
        if os.path.isfile(REALMS_CSV):
            with open(REALMS_CSV, newline='') as f:
                for row in csv.reader(f):
                    if not row:
                        continue
                    if len(row) == 1 and ":" in row[0]:
                        rid, name = row[0].split(":",1)
                    else:
                        rid, name = row[0], row[1]
                    try:
                        self.all_realms[int(rid)] = name.strip()
                    except ValueError:
                        continue

        # Load persisted flags (default True)
        self.flags = {}
        with shelve.open(SETTINGS_DB) as db:
            for rid in self.all_realms:
                self.flags[rid] = db.get(str(rid), True)

        # Build UI
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        # --- Search bar ---
        search_frame = ttk.Frame(frm)
        search_frame.pack(fill="x", pady=(0,5))
        ttk.Label(search_frame, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=(5,0))
        self.search_var.trace_add('write', lambda *args: self._populate_tree())

        # --- Treeview ---
        cols = ("Enabled", "Realm")
        self.tv = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        self.tv.heading("Enabled", text="Enabled")
        self.tv.heading("Realm",   text="Realm (name : id)")
        self.tv.column("Enabled", width=80, anchor="center")
        self.tv.column("Realm",   width=300, anchor="w")
        self.tv.pack(fill="both", expand=True, side="top")

        # Tag styling: realm text always white
        self.tv.tag_configure("on",  background="#2e2e2e", foreground="#ffffff")
        self.tv.tag_configure("off", background="#2e2e2e", foreground="#ffffff")

        # Double-click toggles
        self.tv.bind("<Double-1>", self._on_toggle)

        # Save/Cancel
        btn_frm = ttk.Frame(frm, padding=(0,10))
        btn_frm.pack(fill="x", side="bottom")
        ttk.Button(btn_frm, text="Save",   command=self._save).pack(side="right", padx=5)
        ttk.Button(btn_frm, text="Cancel", command=self.destroy).pack(side="right")

        # Initial population
        self._populate_tree()

    def _populate_tree(self):
        """Clear & repopulate tree based on search filter."""
        q = self.search_var.get().lower()
        self.tv.delete(*self.tv.get_children())

        for rid, name in sorted(self.all_realms.items(), key=lambda x: x[1].lower()):
            if q and q not in name.lower() and q not in str(rid):
                continue
            enabled = self.flags[rid]
            tag = "on" if enabled else "off"
            self.tv.insert(
                "", "end",
                iid=str(rid),
                values=("✓" if enabled else "", f"{name} : {rid}"),
                tags=(tag,)
            )

    def _on_toggle(self, event):
        """Flip the enabled flag for the clicked row."""
        row = self.tv.identify_row(event.y)
        if not row:
            return
        rid = int(row)
        self.flags[rid] = not self.flags[rid]
        # update visual
        self._populate_tree()

    def _save(self):
        """Persist all flags and close."""
        with shelve.open(SETTINGS_DB, writeback=True) as db:
            for rid, val in self.flags.items():
                db[str(rid)] = val
        messagebox.showinfo("Saved", "Realm settings updated.")
        self.destroy()
