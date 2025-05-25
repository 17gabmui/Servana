#!/usr/bin/env python3
"""
Servana - WoW Auction Price Checker GUI (with CSV-based realm list)
"""
import os
import sys
import io
import time
import shelve
import requests
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import threading
from dotenv import load_dotenv

# === Resource Path ===
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

def _load_icon(path, size):
    """
    Load an image from the assets path via resource_path and resize it.
    Returns a PhotoImage for Tkinter.
    """
    try:
        img = Image.open(resource_path(path)).resize(size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception as e:
        print(f"Error loading icon {path}: {e}")
        return None

# === Constants & Cache Settings ===
ROOT_DIR       = os.path.abspath(os.path.dirname(__file__))
CACHE_DIR      = os.path.join(ROOT_DIR, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)
AUCTION_CACHE  = os.path.join(CACHE_DIR, "auction_cache")
TSM_CACHE      = os.path.join(CACHE_DIR, "tsm_cache.db")
NAME_CACHE     = os.path.join(CACHE_DIR, "item_name_cache.db")
PIC_CACHE      = os.path.join(CACHE_DIR, "item_pic_cache.db")

# === API Endpoints ===
BLIZZ_TOKEN_URL  = "https://oauth.battle.net/token"
BLIZZ_AH_URL     = "https://us.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions"
BLIZZ_ITEM_URL   = "https://us.api.blizzard.com/data/wow/item/{itemId}"
BLIZZ_MEDIA_URL  = "https://us.api.blizzard.com/data/wow/media/item/{itemId}"
TSM_TOKEN_URL    = "https://auth.tradeskillmaster.com/oauth2/token"
TSM_REGION_ID    = 1
NAMESPACE        = "dynamic-us"
STATIC_NAMESPACE = "static-us"
LOCALE           = "en_US"

# Load environment
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# Realm manager utilities
from manage_realms_csv import RealmManager, load_selected_realms

# Token cache globals
_cached_blizz_token = None
_blizz_expiry       = 0
_cached_tsm_token   = None
_tsm_expiry         = 0

# ─── Token Helpers ─────────────────────────────────────────────────────────────
def get_blizzard_token():
    global _cached_blizz_token, _blizz_expiry
    now = time.time()
    if _cached_blizz_token and now < _blizz_expiry:
        return _cached_blizz_token
    resp = requests.post(
        BLIZZ_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(os.getenv("BLIZZARD_CLIENT_ID"), os.getenv("BLIZZARD_CLIENT_SECRET"))
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_blizz_token = data["access_token"]
    _blizz_expiry = now + data.get("expires_in", 1800) - 60
    return _cached_blizz_token


def get_tsm_token():
    global _cached_tsm_token, _tsm_expiry
    now = time.time()
    if _cached_tsm_token and now < _tsm_expiry:
        return _cached_tsm_token
    body = {
        "client_id": os.getenv("TSM_CLIENT_ID"),
        "grant_type": "api_token",
        "scope": "app:realm-api app:pricing-api",
        "token": os.getenv("TSM_API_KEY")
    }
    resp = requests.post(TSM_TOKEN_URL, json=body)
    resp.raise_for_status()
    data = resp.json()
    _cached_tsm_token = data["access_token"]
    _tsm_expiry = now + data.get("expires_in", 3600) - 60
    return _cached_tsm_token

# ─── Blizzard & TSM API Helpers ───────────────────────────────────────────────
def get_tsm_region_stats(item_id):
    """
    Fetch TSM marketValue and saleRate, caching results locally.
    """
    key = str(item_id)
    with shelve.open(TSM_CACHE) as db:
        if key in db:
            return db[key]
    token = get_tsm_token()
    resp = requests.get(
        f"https://pricing-api.tradeskillmaster.com/region/{TSM_REGION_ID}/item/{item_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if resp.status_code == 404:
        mv, sr = None, None
    else:
        resp.raise_for_status()
        data = resp.json()
        mv, sr = data.get("marketValue"), data.get("saleRate")
    with shelve.open(TSM_CACHE) as db:
        db[key] = (mv, sr)
    return mv, sr

# ─── Name & Icon Lookup ───────────────────────────────────────────────────────
def get_blizzard_name(item_id):
    key = str(item_id)
    with shelve.open(NAME_CACHE) as db:
        if key in db:
            return db[key]
    token = get_blizzard_token()
    resp = requests.get(
        BLIZZ_ITEM_URL.format(itemId=item_id),
        headers={"Authorization": f"Bearer {token}"},
        params={"namespace": STATIC_NAMESPACE, "locale": LOCALE}
    )
    resp.raise_for_status()
    name = resp.json().get("name", "Unknown Item")
    with shelve.open(NAME_CACHE) as db:
        db[key] = name
    return name


def get_blizzard_pic(item_id):
    key = str(item_id)
    with shelve.open(PIC_CACHE) as db:
        if key in db:
            return db[key]
    token = get_blizzard_token()
    resp = requests.get(
        BLIZZ_MEDIA_URL.format(itemId=item_id),
        headers={"Authorization": f"Bearer {token}"},
        params={"namespace": STATIC_NAMESPACE, "locale": LOCALE}
    )
    resp.raise_for_status()
    assets = resp.json().get("assets", [])
    icon = next((a["value"] for a in assets if a.get("key") == "icon"), None)
    if icon:
        with shelve.open(PIC_CACHE) as db:
            db[key] = icon
    return icon

# ─── Helpers ───────────────────────────────────────────────────────────────────
def format_price(c):
    if c is None:
        return "—"
    return f"{c//10000}g {(c%10000)//100}s {c%100}c"

# Cache auction buyouts locally
def cache_auctions_for_realm(realm_id, auctions_json):
    now = time.time()
    with shelve.open(AUCTION_CACHE) as db:
        realm_key = str(realm_id)
        realm_data = db.get(realm_key, {})
        for auc in auctions_json.get("auctions", []):
            item_id = auc.get("item", {}).get("id")
            buyout  = auc.get("buyout")
            if item_id is not None and buyout is not None:
                existing = realm_data.get(str(item_id))
                realm_data[str(item_id)] = buyout if existing is None else min(existing, buyout)
        realm_data["_ts"] = now
        db[realm_key] = realm_data

# Cache all AH buyouts per realm, rate-limit aware
def cache_all_ah():
    token = get_blizzard_token()
    total = 0
    selected_realms = load_selected_realms()
    for realm_id, realm_name in selected_realms.items():
        try:
            resp = requests.get(
                BLIZZ_AH_URL.format(realm_id=realm_id),
                headers={"Authorization": f"Bearer {token}"},
                params={"namespace": NAMESPACE, "locale": LOCALE}
            )
            resp.raise_for_status()
            data = resp.json()
            cache_auctions_for_realm(realm_id, data)
            total += len(data.get("auctions", []))
            time.sleep(1)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"Rate limited on {realm_name}; skipping.")
                continue
            else:
                raise
    messagebox.showinfo("AH Cache", f"Cached {total} auction entries.")

# ─── Main Query: fetch lowest buyout + TSM stats per item per realm ─────────
def run_query(_, tree, *args):
    # Clear previous entries
    tree.delete(*tree.get_children())

    selected_realms = load_selected_realms()
    for realm_id, realm_name in selected_realms.items():
        try:
            token = get_blizzard_token()
            resp = requests.get(
                BLIZZ_AH_URL.format(realm_id=realm_id),
                headers={"Authorization": f"Bearer {token}"},
                params={"namespace": NAMESPACE, "locale": LOCALE}
            )
            resp.raise_for_status()
            auctions = resp.json().get("auctions", [])

            # Determine lowest buyout per item
            low_map = {}
            for auc in auctions:
                item = auc.get("item", {})
                item_id = item.get("id")
                buyout  = auc.get("buyout")
                if item_id is None or buyout is None:
                    continue
                current = low_map.get(item_id)
                low_map[item_id] = buyout if current is None else min(current, buyout)

            # Insert rows with TSM market average & sale rate
            for item_id, low in low_map.items():
                mv, sr = get_tsm_region_stats(item_id)
                mv_str = format_price(mv) if mv is not None else "—"
                sr_str = f"{sr:.1%}" if sr is not None else "—"
                # Name and icon lookup from static namespace
                name = get_blizzard_name(item_id)
                pic = get_blizzard_pic(item_id)
                tree.insert(
                    "", "end",
                    values=(realm_name, item_id, format_price(low), mv_str, sr_str, name)
                )
            time.sleep(1)
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if hasattr(e, 'response') else None
            if code == 429:
                tree.insert("", "end", values=(realm_name, "Rate Limited", "—", "—", "—", "—"))
                continue
            tree.insert("", "end", values=(realm_name, "Error", str(e), "—", "—", "—"))

    # Populate each realm using only the cached buyout price
    for realm_id, realm_name in selected_realms.items():
        price = get_cached_price(realm_id, item_id)
        if price is None:
            # no cached buyout
            tree.insert(
                "", "end",
                values=(realm_name, "—", "—",
                        format_price(mv) if mv else "—",
                        "—")
            )
            continue

        # compute %Diff vs TSM market value
        if mv is not None:
            diff_pct = (price - mv) / mv * 100
            diff_str = f"{diff_pct:+.1f}%"
            tag = "overpriced" if diff_pct > 0 else "undercut" if diff_pct < 0 else ""
        else:
            diff_str = "—"
            tag = ""

        tree.insert(
            "", "end",
            values=(realm_name,
                    format_price(price),
                    "—",
                    format_price(mv) if mv else "—",
                    diff_str),
            tags=(tag,)
        )

    selected_realms = load_selected_realms()

    try:
        item_id = int(item_input)
    except ValueError:
        messagebox.showerror("Error", "Enter a valid ID or use Show Cache.")
        return

    # Fetch & cache item metadata
    try:
        name = get_blizzard_name(item_id)
    except Exception as e:
        print("DEBUG: name fetch error:", e)
        name = f"Item {item_id}"
    item_label.config(text=name)

    # TSM stats
    try:
        mv, sr = get_tsm_region_stats(item_id)
    except Exception as e:
        print("DEBUG: TSM fetch error:", e)
        mv, sr = None, None
    sale_label.config(text=f"Sale Rate: {sr:.1%}" if sr is not None else "Sale Rate: —")
    mv_label.config(text=f"Market Value: {format_price(mv)}" if mv is not None else "Market Value: —")

    # Populate rows with explicit debug
    for realm_id, realm_name in selected_realms.items():
        try:
            price, qty = get_blizzard_price(realm_id, item_id)
            avg_str = format_price(mv) if mv is not None else "—"
            if price is not None and mv is not None:
                diff_pct = (price - mv) / mv * 100
                diff_str = f"{diff_pct:+.1f}%"
                tag = "overpriced" if diff_pct > 0 else "undercut" if diff_pct < 0 else ""
            else:
                diff_str = "—"
                tag = ""
            print(f"DEBUG row {realm_name}: price={price}, qty={qty}, avg={mv}, diff={diff_str}")
            tree.insert(
                "",
                "end",
                values=(realm_name, format_price(price), qty or 0, avg_str, diff_str),
                tags=(tag,)
            )
        except Exception as e:
            print(f"DEBUG: error inserting {realm_name} ->", e)
            tree.insert("", "end", values=(realm_name, "Error", 0, "—", "—"))

def main():
    root = tk.Tk()
    root.title("Servana - WoW Auction Price Checker")
    root.configure(bg="#1e1e1e")
    root.resizable(True, True)
    root.wm_aspect(16, 9, 16, 9)

    # Pre-load icons
    cog_img    = _load_icon("assets/cogwheel.png",   (24,24))
    bag_img    = _load_icon("assets/Cache_bag.png",  (32,32))
    search_img = _load_icon("assets/Search_button.png", (32,32))
    logo_img   = _load_icon("assets/servana_logo.png",  (246,164))

    # Header bar
    header = tk.Frame(root, bg="#1e1e1e")
    header.pack(fill="x", pady=5)
    tk.Button(
        header, image=cog_img, bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
        command=lambda: RealmManager(root)
    ).pack(side="right", padx=5)
    grab_btn = tk.Button(
        header, text="Grab All AH", bg="#1e1e1e", fg="#ffffff",
        command=lambda: threading.Thread(target=cache_all_ah, daemon=True).start()
    )
    grab_btn.pack(side="left", padx=5)

    paned = tk.PanedWindow(root, orient=tk.HORIZONTAL)
    paned.pack(fill="both", expand=True)

    cache_frame = tk.Frame(paned, bg="#2e2e2e")
    main_frame  = tk.Frame(paned, bg="#1e1e1e")
    paned.add(main_frame)

    cache_visible = {"on": False}
    def toggle_cache():
        if cache_visible["on"]:
            paned.forget(cache_frame)
        else:
            paned.add(cache_frame, before=main_frame)
        cache_visible["on"] = not cache_visible["on"]

    # Cache panel
    tk.Button(
        cache_frame, text="Fill Cache", bg="#1e1e1e", fg="#ffffff",
        command=lambda: threading.Thread(target=cache_all_ah, daemon=True).start()
    ).pack(padx=10, pady=(10,5))
    search_var = tk.StringVar()
    tk.Entry(cache_frame, textvariable=search_var).pack(fill='x', padx=10, pady=5)
    lb = tk.Listbox(cache_frame, bg="#2e2e2e", fg="#dddddd")
    sb = tk.Scrollbar(cache_frame, orient='vertical', command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    lb.pack(side='left', fill='both', expand=True, padx=(10,0), pady=5)
    sb.pack(side='right', fill='y', padx=(0,10), pady=5)

    cache_items = []
    with shelve.open(NAME_CACHE) as db:
        cache_items.extend((k,n) for k,n in db.items())
    cache_items.sort(key=lambda x:int(x[0]))
    def update_list(*args):
        lb.delete(0,'end')
        q = search_var.get().lower()
        for k,n in cache_items:
            if q in n.lower() or q in k:
                lb.insert('end', n)
    search_var.trace_add('write', update_list)
    update_list()
    lb.bind('<Double-1>', lambda e: (
        entry.delete(0,'end'),
        entry.insert(0, next(k for k,n in cache_items if n==lb.get(lb.curselection())))
    ))

    # Main panel
    tk.Label(main_frame, image=logo_img, bg="#1e1e1e").pack(pady=(10,5))
    row = tk.Frame(main_frame, bg="#1e1e1e")
    row.pack(pady=10)
    tk.Button(
        row, image=bag_img, bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
        command=toggle_cache
    ).pack(side="left", padx=(0,5))
    entry = tk.Entry(row, width=20, font=("Arial",12))
    entry.pack(side="left", padx=(0,5))
    search_btn = tk.Button(
        row, image=search_img, bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
        command=lambda: threading.Thread(target=lambda: run_query(entry.get(), tree, item_label, sale_rate_label, market_value_label), daemon=True).start()
    )
    search_btn.pack(side="left")

    item_label  = tk.Label(main_frame, text="Item: —",      font=("Arial",10,"bold"),   bg="#1e1e1e", fg="#ffffff", compound="left")
    sale_rate_label    = tk.Label(main_frame, text="Sale Rate: —",    font=("Arial",10,"italic"), bg="#1e1e1e", fg="#ffffff")
    market_value_label = tk.Label(main_frame, text="Market Value: —", font=("Arial",10,"italic"), bg="#1e1e1e", fg="#ffffff")
    item_label.pack(pady=(5,0))
    sale_rate_label.pack()
    market_value_label.pack()

    # Treeview for per-realm AH + Avg + %Diff
    cols   = ("Realm", "AH Price", "Qty", "Avg", "%Diff")
    widths = (120,  90,        60,   90,    70)
    style = ttk.Style(main_frame)
    style.theme_use("clam")
    style.configure("Custom.Treeview", background="#2e2e2e", fieldbackground="#2e2e2e", foreground="#dddddd", rowheight=24)
    style.configure("Custom.Treeview.Heading", background="#1e1e1e", foreground="#ffffff")
    tree = ttk.Treeview(main_frame, style="Custom.Treeview", columns=cols, show="headings")
    for col, w in zip(cols, widths):
        tree.heading(col, text=col, command=lambda c=col: sort_column(tree, c, False))
        tree.column(col, width=w, anchor="center")
    tree.tag_configure("overpriced", foreground="red")
    tree.tag_configure("undercut",   foreground="green")
    tree.pack(fill="both", expand=True, padx=10, pady=10)
    tree.bind_all("<MouseWheel>", lambda e: tree.yview_scroll(int(-1*(e.delta/120)), "units"))

    tk.Button(
        root,
        text="Run Query",
        command=lambda: threading.Thread(target=lambda: run_query(None, tree), daemon=True).start()
    ).pack(pady=5)

    root.mainloop()

if __name__ == "__main__":
    main()
