#!/usr/bin/env python3
"""
Servana - WoW Auction Price Checker GUI (with CSV-based realm list)
"""
import os
import sys
import io
import time
import shelve
import csv
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

# === Constants & Cache Settings ===
ROOT_DIR       = os.path.abspath(os.path.dirname(__file__))
CACHE_DIR      = os.path.join(ROOT_DIR, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_EXPIRY   = 30 * 60
NAME_CACHE     = os.path.join(CACHE_DIR, "item_name_cache.db")
PIC_CACHE      = os.path.join(CACHE_DIR, "item_pic_cache.db")
REALMS_CSV     = os.path.join(CACHE_DIR, "realms.csv")
AUCTION_CACHE  = os.path.join(CACHE_DIR, "auction_cache")  # base name for shelve

# === API Endpoints ===
BLIZZ_TOKEN_URL = "https://oauth.battle.net/token"
BLIZZ_AH_URL    = "https://us.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions"
BLIZZ_ITEM_URL  = "https://us.api.blizzard.com/data/wow/item/{itemId}"
BLIZZ_MEDIA_URL = "https://us.api.blizzard.com/data/wow/media/item/{itemId}"
TSM_TOKEN_URL   = "https://auth.tradeskillmaster.com/oauth2/token"
TSM_REGION_ID   = 1
NAMESPACE       = "dynamic-us"
LOCALE          = "en_US"

# Load environment
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# Import realm manager utilities (CSV-based)
from manage_realms_csv import RealmManager, load_selected_realms

# Token caching globals
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

# ─── Auction Cache Helpers ────────────────────────────────────────────────────
def cache_auctions_for_realm(realm_id, auctions_json):
    """Store buyout prices keyed by item_id for a realm, and cache names/pics."""
    now = time.time()
    with shelve.open(AUCTION_CACHE) as db:
        realm_key = str(realm_id)
        realm_data = db.get(realm_key, {})
        for auc in auctions_json.get("auctions", []):
            item_id = auc.get("item", {}).get("id")
            buyout  = auc.get("buyout")
            if item_id and buyout is not None:
                # cache price
                realm_data[str(item_id)] = buyout
                # ensure name and pic cached
                try:
                    _ = get_blizzard_name(item_id)
                except Exception:
                    pass
                try:
                    _ = get_blizzard_pic(item_id)
                except Exception:
                    pass
        realm_data["_ts"] = now
        db[realm_key] = realm_data


def get_cached_price(realm_id, item_id):
    """Retrieve buyout price for an item from cache."""
    with shelve.open(AUCTION_CACHE) as db:
        return db.get(str(realm_id), {}).get(str(item_id))


def get_blizzard_price(realm_id, item_id):
    """Get price using cached buyouts, fallback to live fetch if missing, and ensure name/pic cached."""
    price = get_cached_price(realm_id, item_id)
    qty = None
    if price is not None:
        # ensure name and pic cached for this item
        try:
            _ = get_blizzard_name(item_id)
        except Exception:
            pass
        try:
            _ = get_blizzard_pic(item_id)
        except Exception:
            pass
        return price, qty
    # fallback to live fetch and cache
    token = get_blizzard_token()
    resp = requests.get(
        BLIZZ_AH_URL.format(realm_id=realm_id),
        headers={"Authorization": f"Bearer {token}"},
        params={"namespace": NAMESPACE, "locale": LOCALE}
    )
    resp.raise_for_status()
    auctions = resp.json().get("auctions", [])
    prices = [a.get("unit_price") or a.get("buyout") for a in auctions if a.get("item",{}).get("id")==item_id]
    qty    = sum(a.get("quantity",0) for a in auctions if a.get("item",{}).get("id")==item_id)
    price  = min(prices) if prices else None
    cache_auctions_for_realm(realm_id, resp.json())
    # cache name and pic for new item
    if price is not None:
        try:
            _ = get_blizzard_name(item_id)
        except Exception:
            pass
        try:
            _ = get_blizzard_pic(item_id)
        except Exception:
            pass
    return price, qty

# ─── Main Query & GUI Helpers ─────────────────────────────────────────────────
def format_price(c):
    if c is None:
        return "—"
    return f"{c//10000}g {(c%10000)//100}s {c%100}c"

# ─── Blizzard & TSM API Helpers ─────────────────────────────────────────────────
def get_blizzard_name(item_id):
    key = str(item_id)
    with shelve.open(NAME_CACHE) as db:
        if key in db:
            return db[key]
    token = get_blizzard_token()
    resp = requests.get(
        BLIZZ_ITEM_URL.format(itemId=item_id),
        headers={"Authorization": f"Bearer {token}"},
        params={"namespace": NAMESPACE, "locale": LOCALE}
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
        params={"namespace": NAMESPACE, "locale": LOCALE}
    )
    resp.raise_for_status()
    assets = resp.json().get("assets", [])
    icon = next((a["value"] for a in assets if a.get("key") == "icon"), None)
    if icon:
        with shelve.open(PIC_CACHE) as db:
            db[key] = icon
    return icon


def get_tsm_region_stats(item_id):
    token = get_tsm_token()
    resp = requests.get(
        f"https://pricing-api.tradeskillmaster.com/region/{TSM_REGION_ID}/item/{item_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data = resp.json()
    return data.get("marketValue"), data.get("saleRate")


# ─── UI Helpers ───────────────────────────────────────────────────────────────
def _load_icon(path, size):
    img = Image.open(resource_path(path)).resize(size, Image.LANCZOS)
    return ImageTk.PhotoImage(img)

# ─── Treeview Sorting ─────────────────────────────────────────────────────────
def sort_column(tree, col, reverse):
    data = [(tree.set(k, col), k) for k in tree.get_children('')]
    try:
        data.sort(key=lambda t: float(t[0]), reverse=reverse)
    except ValueError:
        data.sort(key=lambda t: t[0], reverse=reverse)
    for index, (_, k) in enumerate(data):
        tree.move(k, '', index)
    tree.heading(col, command=lambda: sort_column(tree, col, not reverse))

# ─── Cache helper for auctions ─────────────────────────────────────────────────
def cache_auctions_for_realm(realm_id, auctions_json):
    """Store buyout prices keyed by item_id for a realm, and cache names/pics."""
    now = time.time()
    with shelve.open(AUCTION_CACHE) as db:
        realm_key = str(realm_id)
        realm_data = db.get(realm_key, {})
        for auc in auctions_json.get("auctions", []):
            item_id = auc.get("item", {}).get("id")
            buyout  = auc.get("buyout")
            if item_id and buyout is not None:
                # cache price
                realm_data[str(item_id)] = buyout
                # ensure name and pic cached
                try:
                    _ = get_blizzard_name(item_id)
                except Exception:
                    pass
                try:
                    _ = get_blizzard_pic(item_id)
                except Exception:
                    pass
        realm_data["_ts"] = now
        db[realm_key] = realm_data


def get_cached_price(realm_id, item_id):
    """Retrieve buyout price for an item from cache."""
    with shelve.open(AUCTION_CACHE) as db:
        return db.get(str(realm_id), {}).get(str(item_id))


def get_blizzard_price(realm_id, item_id):
    """Get price using cached buyouts, fallback to live fetch if missing."""
    price = get_cached_price(realm_id, item_id)
    if price is not None:
        return price, None
    # fallback to live fetch and cache
    token = get_blizzard_token()
    resp = requests.get(
        BLIZZ_AH_URL.format(realm_id=realm_id),
        headers={"Authorization": f"Bearer {token}"},
        params={"namespace": NAMESPACE, "locale": LOCALE}
    )
    resp.raise_for_status()
    auctions = resp.json().get("auctions", [])
    prices = [a.get("unit_price") or a.get("buyout") for a in auctions if a.get("item",{}).get("id")==item_id]
    qty    = sum(a.get("quantity",0) for a in auctions if a.get("item",{}).get("id")==item_id)
    price  = min(prices) if prices else None
    cache_auctions_for_realm(realm_id, resp.json())
    return price, qty

# ─── Cache all AH prices ─────────────────────────────────────────────────────
def cache_all_ah():
    now = time.time()
    token = get_blizzard_token()
    total = 0
    selected_realms = load_selected_realms()
    for realm_id, realm_name in selected_realms.items():
        resp = requests.get(
            BLIZZ_AH_URL.format(realm_id=realm_id),
            headers={"Authorization": f"Bearer {token}"},
            params={"namespace": NAMESPACE, "locale": LOCALE}
        )
        resp.raise_for_status()
        data = resp.json()
        cache_auctions_for_realm(realm_id, data)
        total += len(data.get("auctions", []))
    with shelve.open(BLIZZ_CACHE_DB) as db:
        db["_last_ah_cache_time"] = now
    messagebox.showinfo("AH Cache", f"Cached {total} auction entries.")

# ─── Main Query ────────────────────────────────────────────────────────────────
def run_query(item_input, tree, item_label, sale_label, mv_label):
    selected_realms = load_selected_realms()
    tree.delete(*tree.get_children())
    try:
        item_id = int(item_input)
    except ValueError:
        messagebox.showerror("Error", "Enter a valid ID or use Show Cache.")
        return

    # ─── Direct fetch & cache of item name ────────────────────────────────────
    try:
        token = get_blizzard_token()
        resp = requests.get(
            BLIZZ_ITEM_URL.format(itemId=item_id),
            headers={"Authorization": f"Bearer {token}"},
            params={"namespace": NAMESPACE, "locale": LOCALE}
        )
        resp.raise_for_status()
        name = resp.json().get("name", "Unknown Item")
        with shelve.open(NAME_CACHE) as db:
            db[str(item_id)] = name
    except Exception:
        name = f"Item {item_id}"

    # ─── Direct fetch & cache of item icon URL ────────────────────────────────
    pic_url = None
    try:
        token = get_blizzard_token()
        resp = requests.get(
            BLIZZ_MEDIA_URL.format(itemId=item_id),
            headers={"Authorization": f"Bearer {token}"},
            params={"namespace": NAMESPACE, "locale": LOCALE}
        )
        resp.raise_for_status()
        assets = resp.json().get("assets", [])
        pic_url = next((a["value"] for a in assets if a.get("key") == "icon"), None)
        if pic_url:
            with shelve.open(PIC_CACHE) as db:
                db[str(item_id)] = pic_url
    except Exception:
        pic_url = None

    # ─── TSM stats (unchanged) ───────────────────────────────────────────────
    try:
        mv, sr = get_tsm_region_stats(item_id)
    except requests.exceptions.HTTPError:
        mv, sr = None, None

    # ─── Update UI header ───────────────────────────────────────────────────
    if pic_url:
        try:
            img_data = requests.get(pic_url).content
            photo = ImageTk.PhotoImage(
                Image.open(io.BytesIO(img_data)).resize((24,24), Image.LANCZOS)
            )
            item_label.config(image=photo, text=name)
            item_label.image = photo
        except Exception:
            item_label.config(image="", text=name)
    else:
        item_label.config(image="", text=name)

    sale_label.config(
        text=f"Sale Rate: {sr:.1%}" if sr is not None else "Sale Rate: —"
    )
    mv_label.config(
        text=f"Market Value: {format_price(mv)}" if mv is not None else "Market Value: —"
    )

    # ─── Populate per-realm rows ───────────────────────────────────────────────
    for realm_id, realm_name in selected_realms.items():
        try:
            price, qty = get_blizzard_price(realm_id, item_id)
            if price is not None and mv is not None:
                diff_pct = (price - mv) / mv * 100
                diff_str = f"{diff_pct:+.1f}%"
                tag = "overpriced" if diff_pct > 0 else "undercut" if diff_pct < 0 else ""
            else:
                diff_str = "—"
                tag = ""

            tree.insert("", "end",
                values=(realm_name, format_price(price), qty, diff_str),
                tags=(tag,)
            )
        except Exception:
            tree.insert("", "end",
                values=(realm_name, "Error", 0, "—")
            )

# ─── UI ────────────────────────────────────────────────────────────────────────
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
    # Manage Realms cog
    tk.Button(
        header, image=cog_img, bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
        command=lambda: RealmManager(root)
    ).pack(side="right", padx=5)
    # Grab All AH (threaded)
    def grab_all_ah():
        grab_btn.config(state="disabled")
        try:
            cache_all_ah()
        finally:
            grab_btn.config(state="normal")
    grab_btn = tk.Button(
        header, text="Grab All AH", bg="#1e1e1e", fg="#ffffff",
        command=lambda: threading.Thread(target=grab_all_ah, daemon=True).start()
    )
    grab_btn.pack(side="left", padx=5)

    # ─── Paned layout: cache panel + main panel ───────────────────────────────
    paned = tk.PanedWindow(root, orient=tk.HORIZONTAL)
    paned.pack(fill="both", expand=True)

    # Cache panel (hidden until toggled)
    cache_frame = tk.Frame(paned, bg="#2e2e2e")

    # Main panel
    main_frame = tk.Frame(paned, bg="#1e1e1e")
    paned.add(main_frame)

    # Toggle button in your input row below will call this:
    cache_visible = {"on": False}
    def toggle_cache():
        if cache_visible["on"]:
            paned.forget(cache_frame)
        else:
            paned.add(cache_frame, before=main_frame)
        cache_visible["on"] = not cache_visible["on"]

    # ─── Cache panel contents ─────────────────────────────────────────────────
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

    # ─── Main panel UI ────────────────────────────────────────────────────────

    # Logo
    tk.Label(main_frame, image=logo_img, bg="#1e1e1e").pack(pady=(10,5))

    # Input row
    row = tk.Frame(main_frame, bg="#1e1e1e")
    row.pack(pady=10)
    tk.Button(
        row, image=bag_img, bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
        command=toggle_cache
    ).pack(side="left", padx=(0,5))
    entry = tk.Entry(row, width=20, font=("Arial",12))
    entry.pack(side="left", padx=(0,5))
    # Search button (threaded)
    def threaded_query():
        search_btn.config(state="disabled")
        try:
            run_query(entry.get(), tree, item_label, sale_rate_label, market_value_label)
        finally:
            search_btn.config(state="normal")
    search_btn = tk.Button(
        row, image=search_img, bd=0, bg="#1e1e1e", activebackground="#1e1e1e",
        command=lambda: threading.Thread(target=threaded_query, daemon=True).start()
    )
    search_btn.pack(side="left")

    # Header labels for item + TSM stats
    item_label  = tk.Label(main_frame, text="Item: —",      font=("Arial",10,"bold"),   bg="#1e1e1e", fg="#ffffff", compound="left")
    sale_rate_label    = tk.Label(main_frame, text="Sale Rate: —",    font=("Arial",10,"italic"), bg="#1e1e1e", fg="#ffffff")
    market_value_label = tk.Label(main_frame, text="Market Value: —", font=("Arial",10,"italic"), bg="#1e1e1e", fg="#ffffff")
    item_label.pack(pady=(5,0))
    sale_rate_label.pack()
    market_value_label.pack()

    # Treeview for per-realm AH
    cols = ("Realm","AH Price","Qty","%Diff")
    style = ttk.Style(main_frame)
    style.theme_use("clam")
    style.configure("Custom.Treeview", background="#2e2e2e", fieldbackground="#2e2e2e", foreground="#dddddd", rowheight=24)
    style.configure("Custom.Treeview.Heading", background="#1e1e1e", foreground="#ffffff")
    tree = ttk.Treeview(main_frame, style="Custom.Treeview", columns=cols, show="headings")
    for col,w in zip(cols,(130,90,60,70)):
        tree.heading(col, text=col, command=lambda c=col: sort_column(tree,c,False))
        tree.column(col, width=w, anchor="center")
    tree.tag_configure("overpriced", foreground="red")
    tree.tag_configure("undercut",   foreground="green")
    tree.pack(fill="both", expand=True, padx=10, pady=10)
    tree.bind_all("<MouseWheel>", lambda e: tree.yview_scroll(int(-1*(e.delta/120)), "units"))

    root.mainloop()

if __name__ == "__main__":
    main()