#!/usr/bin/env python3
"""
Servana - WoW Auction Price Checker GUI

Features:
  • Input an item ID or use the Cache panel to browse cached item names
  • Search within cached items using a search bar in the cache window
  • Double-click a cache entry to populate the search field
  • Fetches TSM region stats and Blizzard AH prices across configured realms
  • Caches item names and icons in disk shelves for offline reuse
  • "Fill Cache via CLI" button in cache panel to run external caching script
  • Cache-toggle button (bag icon) to show/hide the cache panel
  • Search button uses a custom image icon
  • Servana logo displayed at top of main UI panel
  • "Cache AH Prices" button to pre-cache all Blizzard AH prices & quantities (hourly)
"""
import os
import sys
import io
import time
import shelve
import subprocess
import requests
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from dotenv import load_dotenv

# === Resource Path === #
def resource_path(relative_path):
    """Get absolute path to resource, supporting PyInstaller bundle and development."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(os.path.dirname(__file__))
    candidates = [
        os.path.join(base_path, relative_path),
        os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path),
        os.path.join(os.getcwd(), relative_path)
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]

# === Constants & Cache Settings ===
# Directory for all cache files
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
CACHE_DIR = os.path.join(ROOT_DIR, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Cache expiration and files
CACHE_EXPIRY   = 30 * 60
TSM_CACHE_DB   = os.path.join(CACHE_DIR, "tsm_cache.db")
BLIZZ_CACHE_DB = os.path.join(CACHE_DIR, "blizz_cache.db")
NAME_CACHE     = os.path.join(CACHE_DIR, "item_name_cache.db")
PIC_CACHE      = os.path.join(CACHE_DIR, "item_pic_cache.db")

# API Endpoints
BLIZZ_TOKEN_URL = "https://oauth.battle.net/token"
BLIZZ_AH_URL    = "https://us.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions"
BLIZZ_ITEM_URL  = "https://us.api.blizzard.com/data/wow/item/{itemId}"
BLIZZ_MEDIA_URL = "https://us.api.blizzard.com/data/wow/media/item/{itemId}"
TSM_TOKEN_URL   = "https://auth.tradeskillmaster.com/oauth2/token"
TSM_REGION_ID   = 1
NAMESPACE       = "dynamic-us"
NAMESPACEN      = "static-us"
LOCALE          = "en_US"

# Cached tokens
_cached_blizz_token = None
_blizz_expiry       = 0
_cached_tsm_token   = None
_tsm_expiry         = 0

# Load environment
load_dotenv()
REALMS = {int(k):v for k,v in (entry.split(":") for entry in os.getenv("REALMS","4:DefaultRealm").split("|"))}

# ---- API Helpers ----
def get_blizzard_token():
    global _cached_blizz_token, _blizz_expiry
    if _cached_blizz_token and time.time() < _blizz_expiry:
        return _cached_blizz_token
    resp = requests.post(
        BLIZZ_TOKEN_URL,
        data={"grant_type":"client_credentials"},
        auth=(os.getenv("BLIZZARD_CLIENT_ID"), os.getenv("BLIZZARD_CLIENT_SECRET"))
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_blizz_token = data["access_token"]
    _blizz_expiry = time.time() + data.get("expires_in",1800) - 60
    return _cached_blizz_token


def get_tsm_token():
    global _cached_tsm_token, _tsm_expiry
    if _cached_tsm_token and time.time() < _tsm_expiry:
        return _cached_tsm_token
    body = {"client_id":os.getenv("TSM_CLIENT_ID"),"grant_type":"api_token",
            "scope":"app:realm-api app:pricing-api","token":os.getenv("TSM_API_KEY")}
    resp = requests.post(TSM_TOKEN_URL, json=body)
    resp.raise_for_status()
    data = resp.json()
    _cached_tsm_token = data["access_token"]
    _tsm_expiry = time.time() + data.get("expires_in",3600) - 60
    return _cached_tsm_token


def format_price(c):
    if c is None: return "—"
    return f"{c//10000}g {(c%10000)//100}s {c%100}c"


def get_blizzard_name(item_id):
    key = str(item_id)
    with shelve.open(NAME_CACHE) as db:
        if key in db:
            return db[key]
    token = get_blizzard_token()
    resp = requests.get(
        BLIZZ_ITEM_URL.format(itemId=item_id),
        headers={"Authorization":f"Bearer {token}"},
        params={"namespace":NAMESPACEN, "locale":LOCALE}
    )
    resp.raise_for_status()
    name = resp.json().get("name","Unknown Item")
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
        headers={"Authorization":f"Bearer {token}"},
        params={"namespace":NAMESPACEN, "locale":LOCALE}
    )
    resp.raise_for_status()
    assets = resp.json().get("assets",[])
    icon = next((a["value"] for a in assets if a.get("key")=="icon"), None)
    if icon:
        with shelve.open(PIC_CACHE) as db:
            db[key] = icon
    return icon


def get_tsm_region_stats(item_id):
    token = get_tsm_token()
    resp = requests.get(f"https://pricing-api.tradeskillmaster.com/region/{TSM_REGION_ID}/item/{item_id}",
                        headers={"Authorization":f"Bearer {token}"})
    if resp.status_code==404: return None, None
    resp.raise_for_status()
    data = resp.json()
    return data.get("marketValue"), data.get("saleRate")


def get_blizzard_price(realm_id, item_id):
    key = f"{realm_id}:{item_id}"
    with shelve.open(BLIZZ_CACHE_DB) as db:
        entry = db.get(key)
        if entry and time.time()-entry.get("timestamp",0)<CACHE_EXPIRY:
            return entry["price"], entry["quantity"]
    token = get_blizzard_token()
    resp = requests.get(
        BLIZZ_AH_URL.format(realm_id=realm_id),
        headers={"Authorization":f"Bearer {token}"},
        params={"namespace":NAMESPACE, "locale":LOCALE}
    )
    resp.raise_for_status()
    auctions = resp.json().get("auctions",[])
    prices = [a.get("unit_price") or a.get("buyout") for a in auctions if a["item"]["id"]==item_id]
    qty = sum(a.get("quantity",0) for a in auctions if a["item"]["id"]==item_id)
    price = min(prices) if prices else None
    with shelve.open(BLIZZ_CACHE_DB) as db:
        db[key] = {"price":price, "quantity":qty, "timestamp":time.time()}
    return price, qty

# ---- GUI: Show Cache Window with Search Bar ----
def show_cache(entry_widget):
    win = tk.Toplevel()
    win.title("Item Cache")
    win.geometry("400x500")

    # Button to run external CLI cache-filler
    btn_frame = tk.Frame(win)
    btn_frame.pack(fill="x", pady=(5,10))
    def run_cli_fill():
        script = resource_path("assets/servana_cli.py")
        for realm_id in REALMS:
            subprocess.run([sys.executable, script, "--realm", str(realm_id)])
        # reload items from shelf
        items.clear()
        with shelve.open(NAME_CACHE) as db:
            for k,n in db.items():
                items.append((k, n))
        items.sort(key=lambda x: int(x[0]))
        update_list()
        messagebox.showinfo("Cache Script", "CLI caching complete!")
    fill_btn = tk.Button(btn_frame, text="Fill Cache via CLI", command=run_cli_fill)
    fill_btn.pack(side="left", padx=5)

    # Search bar
    search_var = tk.StringVar()
    search_entry = tk.Entry(win, textvariable=search_var)
    search_entry.pack(fill="x", padx=5)

    lb = tk.Listbox(win, width=50, height=20)
    sb = tk.Scrollbar(win, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    # Load all cached items
    items = []
    with shelve.open(NAME_CACHE) as db:
        for key, name in db.items():
            items.append((key, name))
    items.sort(key=lambda x: int(x[0]))

    def update_list(*args):
        query = search_var.get().lower()
        lb.delete(0, "end")
        for key, name in items:
            if query in name.lower() or query in key:
                lb.insert("end", name)
    search_var.trace_add("write", update_list)
    update_list()

    def on_select(evt):
        sel = lb.curselection()
        if not sel:
            return
        chosen_name = lb.get(sel[0])
        key = next(k for k, n in items if n == chosen_name)
        entry_widget.delete(0, "end")
        entry_widget.insert(0, key)
        win.destroy()
    lb.bind('<Double-Button-1>', on_select)

# ---- GUI: Main & run_query ----
def run_query(item_input, tree, item_label, sale_label, mv_label):
    tree.delete(*tree.get_children())
    try:
        item_id = int(item_input)
    except ValueError:
        messagebox.showerror("Error", "Enter a valid ID or use Show Cache.")
        return

    # Fetch data
    name = get_blizzard_name(item_id)
    sale, rate = get_tsm_region_stats(item_id)
    pic_url = get_blizzard_pic(item_id)

    # Update labels
    item_label.config(text=name, image=None)
    if pic_url:
        img_data = requests.get(pic_url).content
        img = Image.open(io.BytesIO(img_data)).resize((24, 24), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        item_label.config(image=photo)
        item_label.image = photo
    sale_label.config(text=f"Sale Rate: {rate:.1%}" if rate is not None else "Sale Rate: —")
    mv_label.config(text=f"Market Value: {format_price(sale)}" if sale is not None else "Market Value: —")

    # Populate perrealm prices and diff
    for rid, rname in REALMS.items():
        try:
            price, qty = get_blizzard_price(rid, item_id)
            diff = "—"
            tag = ""
            if price is not None and sale:
                d = (price - sale) / sale * 100
                diff = f"{d:+.1f}%"
                tag = "overpriced" if d > 0 else "undercut" if d < 0 else ""
            tree.insert('', 'end', values=(rname, format_price(price), qty, diff), tags=(tag,))
        except Exception:
            tree.insert('', 'end', values=(rname, "Error", 0, "—"))

# ---- GUI Helpers ----
def run_cli_fill(items, update_list_callback):
    script = resource_path("assets/Cache_loader.py")
    for rid in REALMS:
        subprocess.run([sys.executable, script, "--realm", str(rid)])
    items.clear()
    with shelve.open(NAME_CACHE) as db:
        items.extend((k,n) for k,n in db.items())
    items.sort(key=lambda x:int(x[0]))
    update_list_callback()
    messagebox.showinfo("Cache Script","CLI caching complete!")


def cache_all_ah():
    now = time.time()
    with shelve.open(BLIZZ_CACHE_DB) as db:
        last = db.get("_last_ah_cache_time",0)
        if now-last<3600:
            messagebox.showinfo("AH Cache","Cached less than an hour ago.")
            return
        token = get_blizzard_token()
        new_count=0
        for realm in REALMS:
            resp = requests.get(
                BLIZZ_AH_URL.format(realm_id=realm),
                headers={"Authorization":f"Bearer {token}"},
                params={"namespace":NAMESPACE,"locale":LOCALE}
            )
            resp.raise_for_status()
            for a in resp.json().get("auctions",[]):
                key=f"{realm}:{a['item']['id']}"
                price=a.get("unit_price")or a.get("buyout")
                qty=a.get("quantity",0)
                if key not in db: new_count+=1
                db[key]={"price":price,"quantity":qty,"timestamp":now}
        db["_last_ah_cache_time"]=now
    messagebox.showinfo("AH Cache",f"Cached {new_count} new entries.")

# ---- Main Application ----
def main():
    root=tk.Tk()
    root.title("Servana - WoW Auction Price Checker")
    root.configure(bg="#1e1e1e")
    root.resizable(True,True)
    root.wm_aspect(16,9,16,9)

    state={"visible":False}
    paned=tk.PanedWindow(root,orient=tk.HORIZONTAL)
    paned.pack(fill="both",expand=True)
    cache_frame=tk.Frame(paned,bg="#2e2e2e",width=250)
    main_frame=tk.Frame(paned,bg="#1e1e1e")
    paned.add(main_frame)

    def toggle_cache():
        if state["visible"]:
            paned.forget(cache_frame)
        else:
            paned.forget(main_frame)
            paned.add(cache_frame)
            paned.add(main_frame)
        state["visible"]=not state["visible"]

    # Logo and icons
    logo=ImageTk.PhotoImage(Image.open(resource_path("assets/servana_logo.png")).resize((246,164),Image.LANCZOS))
    tk.Label(main_frame,image=logo,bg="#1e1e1e").pack(pady=(10,5))
    bag=ImageTk.PhotoImage(Image.open(resource_path("assets/Cache_bag.png")).resize((32,32),Image.LANCZOS))
    search_img=ImageTk.PhotoImage(Image.open(resource_path("assets/Search_button.png")).resize((32,32),Image.LANCZOS))

    # Input row
    row=tk.Frame(main_frame,bg="#1e1e1e");row.pack(pady=10)
    tk.Button(row,image=bag,command=toggle_cache,bg="#1e1e1e",bd=0,activebackground="#1e1e1e").pack(side="left",padx=(0,5))
    entry=tk.Entry(row,width=20,font=("Arial",12));entry.pack(side="left",padx=(0,5))
    tk.Button(row,image=search_img,command=lambda:run_query(entry.get(),tree,item_label,sale_rate_label,market_value_label),bg="#2e2e2e",bd=0,activebackground="#444444").pack(side="left")

    # Cache panel contents
    tk.Button(cache_frame,text="Fill Cache",command=lambda:run_cli_fill(cache_items,update_cache_list),bg="#1e1e1e",fg="#ffffff").pack(padx=10,pady=5)
    tk.Button(cache_frame,text="Cache AH Prices",command=cache_all_ah,bg="#1e1e1e",fg="#ffffff").pack(padx=10,pady=(0,5))
    search_var=tk.StringVar();tk.Entry(cache_frame,textvariable=search_var).pack(fill="x",padx=10,pady=5)
    lb=tk.Listbox(cache_frame,bg="#2e2e2e",fg="#dddddd");sb=tk.Scrollbar(cache_frame,orient="vertical",command=lb.yview)
    lb.configure(yscrollcommand=sb.set);lb.pack(side="left",fill="both",expand=True,padx=(10,0),pady=5);sb.pack(side="right",fill="y",padx=(0,10),pady=5)
    cache_items=[]
    def update_cache_list(*args):
        lb.delete(0,"end");q=search_var.get().lower()
        for k,n in cache_items:
            if q in n.lower() or q in k:lb.insert("end",n)
    with shelve.open(NAME_CACHE) as db:
        cache_items.extend((k,n) for k,n in db.items())
    cache_items.sort(key=lambda x:int(x[0]));search_var.trace_add("write",update_cache_list);update_cache_list()
    lb.bind('<Double-Button-1>',lambda e:(entry.delete(0,"end"),entry.insert(0,next(k for k,n in cache_items if n==lb.get(lb.curselection())))))

    # Status & treeview
    item_label=tk.Label(main_frame,text="Item: —",font=("Arial",10,"bold"),bg="#1e1e1e",fg="#ffffff");item_label.pack()
    sale_rate_label=tk.Label(main_frame,text="Sale Rate: —",font=("Arial",10,"italic"),bg="#1e1e1e",fg="#ffffff");sale_rate_label.pack()
    market_value_label=tk.Label(main_frame,text="Market Value: —",font=("Arial",10,"italic"),bg="#1e1e1e",fg="#ffffff");market_value_label.pack()
    cols=("Realm","AH Price","Qty","%Diff");style=ttk.Style(main_frame);style.theme_use("clam")
    style.configure("Custom.Treeview",background="#2e2e2e",fieldbackground="#2e2e2e",foreground="#dddddd",rowheight=24)
    style.configure("Custom.Treeview.Heading",background="#1e1e1e",foreground="#ffffff",relief="flat")
    style.map("Custom.Treeview",background=[("selected","#555555")],foreground=[("selected","#ffffff")])
    tree=ttk.Treeview(main_frame,style="Custom.Treeview",columns=cols,show="headings")
    for c,w in zip(cols,(130,90,60,70)):tree.heading(c,text=c);tree.column(c,width=w,anchor="center")
    tree.tag_configure("overpriced",foreground="red");tree.tag_configure("undercut",foreground="green");tree.pack(fill="both",expand=True,padx=10,pady=10)
    tree.bind_all("<MouseWheel>",lambda e:tree.yview_scroll(int(-1*(e.delta/120)),"units"))

    root.mainloop()

if __name__=='__main__':
    main()
