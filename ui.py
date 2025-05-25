#!/usr/bin/env python3
import threading
import io
import requests
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import shelve

from utils import _load_icon, format_price
from api import (
    get_tsm_region_stats,
    get_blizzard_name,
    get_blizzard_pic,
    NAME_CACHE,
    cache_selected_realms_auctions,
    cache_realm_auctions
)
from cache import get_cached_price
from manage_realms_csv import RealmManager, load_selected_realms

class ServanaApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Servana - WoW Auction Price Checker")
        self.root.configure(bg="#1e1e1e")
        self.root.resizable(True, True)
        self.root.wm_aspect(16, 9, 16, 9)
        # Track cache-panel build state
        self.cache_built = False
        self._build_ui()

    def _build_ui(self):
        # Pre-load icons
        self.cog_img         = _load_icon("assets/cogwheel.png",   (24,24))
        self.bag_img         = _load_icon("assets/Cache_bag.png",  (32,32))
        self.search_img      = _load_icon("assets/Search_button.png", (32,32))
        self.logo_img        = _load_icon("assets/servana_logo.png",  (246,164))
        self.placeholder_img = _load_icon("assets/placeholder.png",    (48,48))

        # Header with RealmManager cog
        header = tk.Frame(self.root, bg="#1e1e1e")
        header.pack(fill="x", pady=5)
        tk.Button(
            header,
            image=self.cog_img,
            width=24, height=24,
            bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
            command=self._open_realm_manager
        ).pack(side="right", padx=5)

        # Paned window for cache and main panels
        self.paned = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            bg="#1e1e1e",
            sashrelief=tk.FLAT,
            bd=0
        )
        self.paned.pack(fill="both", expand=True)

        # Cache panel (hidden until toggled)
        self.cache_frame   = tk.Frame(self.paned, bg="#2e2e2e", width=300)
        self.cache_visible = False

        # Main panel
        self.main = tk.Frame(self.paned, bg="#1e1e1e")
        self.paned.add(self.main)

        # Logo
        tk.Label(
            self.main,
            image=self.logo_img,
            bg="#1e1e1e",
            width=246, height=164
        ).pack(pady=(10,5))

        # Input row with cache toggle and search
        row = tk.Frame(self.main, bg="#1e1e1e")
        row.pack(pady=10)
        tk.Button(
            row,
            image=self.bag_img,
            width=32, height=32,
            bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
            command=self._toggle_cache
        ).pack(side="left", padx=(0,5))
        self.entry = tk.Entry(row, width=20, font=("Arial",12))
        self.entry.pack(side="left", padx=(0,5))
        tk.Button(
            row,
            image=self.search_img,
            width=32, height=32,
            bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
            command=lambda: threading.Thread(target=self._run_query, daemon=True).start()
        ).pack(side="left")

        # Item info panel
        info = tk.Frame(self.main, bg="#1e1e1e")
        info.pack(fill="x", pady=(0,10))
        self.item_img = tk.Label(info, image=self.placeholder_img, bg="#1e1e1e")
        self.item_img.image = self.placeholder_img
        self.item_img.pack(side="left", padx=(10,5))
        text_col = tk.Frame(info, bg="#1e1e1e")
        text_col.pack(side="left", fill="x", expand=True)
        self.item_name = tk.Label(
            text_col, text="Item: —", font=("Arial",10,"bold"),
            bg="#1e1e1e", fg="#ffffff"
        )
        self.item_name.pack(anchor="w")
        self.mv_label = tk.Label(
            text_col, text="Market Value: —", font=("Arial",10,"italic"),
            bg="#1e1e1e", fg="#ffffff"
        )
        self.mv_label.pack(anchor="w")
        self.sale_label = tk.Label(
            text_col, text="Sale Rate: —", font=("Arial",10,"italic"),
            bg="#1e1e1e", fg="#ffffff"
        )
        self.sale_label.pack(anchor="w")

        # Treeview: Realm, Buyout, Diff
        cols   = ("Realm", "Buyout", "Diff")
        widths = (180,      100,       80)
        style = ttk.Style(self.main)
        style.theme_use("clam")
        style.configure(
            "Custom.Treeview",
            background="#2e2e2e", fieldbackground="#2e2e2e",
            foreground="#dddddd", rowheight=24
        )
        style.configure("Custom.Treeview.Heading", background="#1e1e1e", foreground="#ffffff")
        self.tree = ttk.Treeview(self.main, style="Custom.Treeview", columns=cols, show="headings")
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c, command=lambda c=c: self._sort_column(c, False))
            self.tree.column(c, width=w, anchor="center")
        self.tree.tag_configure("overpriced", foreground="red")
        self.tree.tag_configure("undercut",   foreground="green")
        self.tree.pack(fill="both", expand=True)

    def _build_cache_panel(self):
        # Construct cache-panel widgets once
        btn = tk.Button(
            self.cache_frame, text="Fill Cache",
            bg="#1e1e1e", fg="#ffffff",
            command=lambda: threading.Thread(
                target=self._fill_cache, daemon=True
            ).start()
        )
        btn.pack(pady=(10,5))

        self.cache_search_var = tk.StringVar()
        tk.Entry(self.cache_frame, textvariable=self.cache_search_var).pack(fill='x', padx=5, pady=5)

        self.cache_listbox = tk.Listbox(self.cache_frame, bg="#2e2e2e", fg="#dddddd")
        self.cache_listbox.pack(fill='both', expand=True, padx=5, pady=5)

        items = []
        with shelve.open(NAME_CACHE) as db:
            items.extend((k, v) for k, v in db.items())
        items.sort(key=lambda x: int(x[0]))

        def update_list(*args):
            self.cache_listbox.delete(0, 'end')
            q = self.cache_search_var.get().lower()
            for k, n in items:
                if q in n.lower() or q in k:
                    self.cache_listbox.insert('end', f"{k} - {n}")

        self.cache_search_var.trace_add('write', update_list)
        update_list()

        self.cache_listbox.bind(
            '<Double-1>',
            lambda e: (
                self.entry.delete(0, 'end'),
                self.entry.insert(0, self.cache_listbox.get(self.cache_listbox.curselection()).split(' - ',1)[0]),
                self._toggle_cache()
            )
        )

    def _toggle_cache(self):
        # Build panel once
        if not self.cache_built:
            self._build_cache_panel()
            self.cache_built = True

        # Show or hide
        if self.cache_visible:
            self.paned.forget(self.cache_frame)
        else:
            self.paned.add(self.cache_frame, before=self.main)
        self.cache_visible = not self.cache_visible

    def _open_realm_manager(self):
        rm = RealmManager(self.root)
        for win in self.root.winfo_children():
            if isinstance(win, tk.Toplevel):
                x = self.root.winfo_x() + self.root.winfo_width()
                y = self.root.winfo_y()
                win.geometry(f"+{x}+{y}")
                break

    def _fill_cache(self):
        try:
            cache_selected_realms_auctions()
            messagebox.showinfo("Cache Complete", "Realm auctions have been cached.")
        except Exception as e:
            messagebox.showerror("Cache Error", str(e))

    def _sort_column(self, col, reverse):
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        try:
            data.sort(key=lambda t: float(t[0].strip('gsc%+–—')), reverse=reverse)
        except:
            data.sort(key=lambda t: t[0], reverse=reverse)
        for i, (_, k) in enumerate(data):
            self.tree.move(k, '', i)
        self.tree.heading(col, command=lambda: self._sort_column(col, not reverse))

    def _run_query(self):
        text = self.entry.get().strip()
        try:
            item_id = int(text)
        except ValueError:
            messagebox.showerror("Error", "Enter a valid item ID.")
            return
        self.tree.delete(*self.tree.get_children())
        # fetch item info
        name = get_blizzard_name(item_id)
        pic = get_blizzard_pic(item_id)
        if pic:
            data = requests.get(pic).content
            img = ImageTk.PhotoImage(
                Image.open(io.BytesIO(data)).resize((48,48), Image.LANCZOS)
            )
            self.item_img.config(image=img)
            self.item_img.image = img
        else:
            self.item_img.config(image=self.placeholder_img)
            self.item_img.image = self.placeholder_img
        self.item_name.config(text=name)
        # fetch & display stats
        mv, sr = get_tsm_region_stats(item_id)
        self.mv_label.config(
            text=f"Market Value: {format_price(mv)}" if mv else "Market Value: —"
        )
        self.sale_label.config(
            text=f"Sale Rate: {sr:.1%}" if sr else "Sale Rate: —"
        )
        # populate tree
        for rid, rname in load_selected_realms().items():
            price = get_cached_price(rid, item_id)
            if price is None:
                # fetch live auction data and cache
                try:
                    realm_data = cache_realm_auctions(rid)
                    price = realm_data.get(str(item_id))
                except Exception:
                    price = None
            if price is None:
                buy, diff, tag = "—", "—", ""
            else:
                buy = format_price(price)
                if mv is not None:
                    diff_pct = (price - mv) / mv * 100
                    diff = f"{diff_pct:+.1f}%"
                    tag = "overpriced" if diff_pct > 0 else "undercut" if diff_pct < 0 else ""
                else:
                    diff, tag = "—", ""
            self.tree.insert(
                "",
                "end",
                values=(rname, buy, diff),
                tags=(tag,)
            )

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    ServanaApp().run()
