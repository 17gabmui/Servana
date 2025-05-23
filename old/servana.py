import requests
import shelve
import sys
import os
import io
import time
from dotenv import load_dotenv
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

# === Constants & Cache Settings ===
CACHE_EXPIRY = 30 * 60  # 30 minutes in seconds
TSM_CACHE_DB = "tsm_cache.db"
BLIZZ_CACHE_DB = "blizz_cache.db"

BLIZZ_TOKEN_URL = "https://oauth.battle.net/token"
BLIZZ_AH_URL = "https://us.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions"
BLIZZ_AH_NAME = "https://us.api.blizzard.com/data/wow/item/{itemId}"
BLIZZ_AH_PICS = "https://us.api.blizzard.com/data/wow/media/item/{itemId}"
TSM_TOKEN_URL = "https://auth.tradeskillmaster.com/oauth2/token"
TSM_REGION_ID = 1
NAMESPACE = "dynamic-us"
NAMESPACEN = "static-us"
LOCALE = "en_US"

cached_tsm_token = None
cached_tsm_token_expiry = 0
cached_blizz_token = None
cached_blizz_token_expiry = 0


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath('.')
    return os.path.join(base_path, relative_path)

# Load environment variables
def load_env():
    load_dotenv()
    global BLIZZARD_CLIENT_ID, BLIZZARD_CLIENT_SECRET, TSM_CLIENT_ID, TSM_API_KEY
    BLIZZARD_CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
    BLIZZARD_CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")
    TSM_CLIENT_ID = os.getenv("TSM_CLIENT_ID")
    TSM_API_KEY = os.getenv("TSM_API_KEY")
load_env()


def load_realms_from_env():
    realms_env = os.getenv("REALMS", "")
    realms = {}
    for entry in realms_env.split("|"):
        try:
            realm_id_str, name = entry.split(":")
            realms[int(realm_id_str)] = name
        except ValueError:
            continue
    return realms

REALMS = load_realms_from_env()


def get_blizzard_token():
    global cached_blizz_token, cached_blizz_token_expiry
    if cached_blizz_token and time.time() < cached_blizz_token_expiry:
        return cached_blizz_token
    response = requests.post(
        BLIZZ_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(BLIZZARD_CLIENT_ID, BLIZZARD_CLIENT_SECRET)
    )
    response.raise_for_status()
    result = response.json()
    cached_blizz_token = result["access_token"]
    cached_blizz_token_expiry = time.time() + result.get("expires_in", 1800) - 60
    return cached_blizz_token


def get_tsm_access_token():
    global cached_tsm_token, cached_tsm_token_expiry
    if cached_tsm_token and time.time() < cached_tsm_token_expiry:
        return cached_tsm_token
    data = {
        "client_id": TSM_CLIENT_ID,
        "grant_type": "api_token",
        "scope": "app:realm-api app:pricing-api",
        "token": TSM_API_KEY
    }
    response = requests.post(TSM_TOKEN_URL, json=data, headers={"Content-Type": "application/json"})
    response.raise_for_status()
    result = response.json()
    cached_tsm_token = result["access_token"]
    cached_tsm_token_expiry = time.time() + result.get("expires_in", 3600) - 60
    return cached_tsm_token


def get_tsm_region_stats(item_id, region_id=TSM_REGION_ID):
    key = str(item_id)
    with shelve.open(TSM_CACHE_DB) as cache:
        entry = cache.get(key)
        if entry and time.time() - entry["timestamp"] < CACHE_EXPIRY:
            return entry["marketValue"], entry["saleRate"]
    access_token = get_tsm_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://pricing-api.tradeskillmaster.com/region/{region_id}/item/{item_id}"
    response = requests.get(url, headers=headers)
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    data = response.json()
    mv = data.get("marketValue")
    sr = data.get("saleRate")
    with shelve.open(TSM_CACHE_DB) as cache:
        cache[key] = {"marketValue": mv, "saleRate": sr, "timestamp": time.time()}
    return mv, sr


def get_blizzard_price(realm_id, item_id, token):
    key = f"{realm_id}:{item_id}"
    with shelve.open(BLIZZ_CACHE_DB) as cache:
        entry = cache.get(key)
        if entry and time.time() - entry["timestamp"] < CACHE_EXPIRY:
            return entry["price"], entry["quantity"]
    url = BLIZZ_AH_URL.format(realm_id=realm_id)
    headers = {"Authorization": f"Bearer {token}"}
    params = {"namespace": NAMESPACE, "locale": LOCALE}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    auctions = response.json().get("auctions", [])
    matches = [a.get("unit_price") or a.get("buyout") for a in auctions if a["item"]["id"] == item_id]
    quantity = sum(a.get("quantity", 0) for a in auctions if a["item"]["id"] == item_id)
    price = min(matches) if matches else None
    with shelve.open(BLIZZ_CACHE_DB) as cache:
        cache[key] = {"price": price, "quantity": quantity, "timestamp": time.time()}
    return price, quantity

def get_blizzard_name(item_id, token):
    with shelve.open("item_name_cache.db") as cache:
        key = str(item_id)
        if key in cache:
            return cache[key]

        url = BLIZZ_AH_NAME.format(itemId=item_id)
        headers = {"Authorization": f"Bearer {token}"}
        params = {"namespace": NAMESPACEN, "locale": LOCALE}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        item_name = response.json().get("name", "Unknown Item")
        cache[key] = item_name  # Store in disk cache
        return item_name
    
def get_blizzard_pic(item_id, token):
    with shelve.open("item_pic_cache.db") as cache:
        key = str(item_id)
        if key in cache:
            return cache[key]

        url = BLIZZ_AH_PICS.format(itemId=item_id)
        headers = {"Authorization": f"Bearer {token}"}
        params = {"namespace": NAMESPACEN, "locale": LOCALE}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        data = response.json() 
        assets = data.get("assets", [])
        icon_url = next((a["value"] for a in assets if a.get("key") == "icon"), None)

        if icon_url:
            cache[key] = icon_url
        return icon_url

def format_price(c):
    if c is None:
        return "—"
    return f"{c // 10000}g {(c % 10000) // 100}s {c % 100}c"

def sort_treeview(tree, col, reverse):
    data = [(tree.set(k, col), k) for k in tree.get_children('')]

    def convert(value):
        try:
            if "%" in value:
                return float(value.replace('%', '').replace('+', '').replace('−', '-'))
            if 'g' in value:
                g, s, c = [int(x.strip('gsc ')) for x in value.replace('—', '0g 0s 0c').split()]
                return g * 10000 + s * 100 + c
            return int(value)
        except:
            return value.lower() if isinstance(value, str) else value

    data.sort(key=lambda t: convert(t[0]), reverse=reverse)
    for index, (_, k) in enumerate(data):
        tree.move(k, '', index)

    tree.heading(col, command=lambda: sort_treeview(tree, col, not reverse))

def run_query(item_id_str, tree, item_label, sale_rate_label, market_value_label):
    tree.delete(*tree.get_children())

    try:
        item_id = int(item_id_str.strip())
    except ValueError:
        messagebox.showerror("Error", "Invalid item ID")
        return

    try:
        blizz_token = get_blizzard_token()

        # Get name and TSM stats first
        item_name = get_blizzard_name(item_id, blizz_token)
        tsm_region_price, tsm_sale_rate = get_tsm_region_stats(item_id)

        # Fetch icon URL and load image
        icon_url = get_blizzard_pic(item_id, blizz_token)

        item_label.config(text=item_name, image=None)
        item_label.image = None  # clear old image

        if icon_url:
            try:
                icon_response = requests.get(icon_url)
                icon_response.raise_for_status()
                img_data = Image.open(io.BytesIO(icon_response.content)).resize((24, 24), Image.LANCZOS)
                icon_photo = ImageTk.PhotoImage(img_data)

                # Set icon + text in label (left-aligned)
                item_label.config(image=icon_photo)
                item_label.image = icon_photo
            except Exception as e:
                print(f"Failed to load icon: {e}")

    except Exception as e:
        messagebox.showerror("Error", f"Failed to fetch item data: {e}")
        return

    # Update pricing labels
    sale_rate_label.config(text=f"Sale Rate: {tsm_sale_rate:.1%}" if tsm_sale_rate else "Sale Rate: —")
    market_value_label.config(text=f"Market Value: {format_price(tsm_region_price)}" if tsm_region_price else "Market Value: —")

    for realm_id, realm_name in REALMS.items():
        try:
            blizz_price, quantity = get_blizzard_price(realm_id, item_id, blizz_token)
            percent_diff = "—"
            tag = ""

            if blizz_price is not None and tsm_region_price and tsm_region_price != 0:
                diff = (blizz_price - tsm_region_price) / tsm_region_price * 100
                percent_diff = f"{diff:+.1f}%"
                tag = "overpriced" if diff > 0 else "undercut" if diff < 0 else ""

            tree.insert("", "end", values=(realm_name, format_price(blizz_price), quantity, percent_diff), tags=(tag,))
        except Exception:
            tree.insert("", "end", values=(realm_name, "Error", 0, "—"))

def main():
    root = tk.Tk()
    root.title("Servana - WoW Auction Price Checker")
    root.geometry("370x500")
    root.resizable(True, True)

    # === DARK MODE STYLING ===
    bg_color = "#1e1e1e"
    fg_color = "#ffffff"
    search_color = "#A9A9A9"
    accent_color = "#1d1d1d"
    transparent = "00FFFFFF"
    highlight_color = "#3c3c3c"
    root.configure(bg=bg_color)

    # === CENTERED INPUT + LOGO BUTTON ===
    frm_input = tk.Frame(root, bg=bg_color)
    frm_input.pack(pady=10)

    entry = tk.Entry(frm_input, font=("Arial", 12), width=30, justify="center",
                     bg=search_color, fg=bg_color, insertbackground=fg_color, relief="flat")
    entry.pack(pady=5)

    try:
        logo_button_img = Image.open(resource_path("assets/servana_logo.png"))
        resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
        logo_button_img = logo_button_img.resize((250, 140), resample=resample_filter)
        logo_button_photo = ImageTk.PhotoImage(logo_button_img)

        btn_logo = tk.Button(
            frm_input, image=logo_button_photo,
            command=lambda: run_query(entry.get(), tree, item_label, sale_rate_label, market_value_label),
            borderwidth=0, highlightthickness=0, cursor="hand2", bg=bg_color, activebackground=bg_color
        )
        btn_logo.image = logo_button_photo
        btn_logo.pack(pady=(0, 5))
    except Exception as e:
        print(f"Could not load logo search button: {e}")
        btn = tk.Button(frm_input, text="Search",
                        font=("Arial", 10, "bold"),
                        command=lambda: run_query(entry.get(), tree, item_label, sale_rate_label, market_value_label),
                        bg=highlight_color, fg=fg_color, activebackground=transparent, activeforeground=fg_color)
        btn.pack(pady=(0, 5))

    label_frame = tk.Frame(frm_input, bg=bg_color)
    label_frame.pack(fill="x", padx=0)

    item_label = tk.Label(label_frame, text="Item: —", font=("Arial", 10, "bold"),
                      bg=bg_color, fg=fg_color, compound="left") 
    item_label.pack(side="left")

    right_label_frame = tk.Frame(label_frame, bg=bg_color)
    right_label_frame.pack(side="right")

    sale_rate_label = tk.Label(right_label_frame, text="Sale Rate: —", font=("Arial", 10, "italic"), bg=bg_color, fg=fg_color)
    sale_rate_label.pack(anchor="e")

    market_value_label = tk.Label(right_label_frame, text="Market Value: —", font=("Arial", 10, "italic"), bg=bg_color, fg=fg_color)
    market_value_label.pack(anchor="e")


    columns = ("Realm", "AH Price", "Qty", "%Diff")
    tree = ttk.Treeview(root, columns=columns, show="headings")

    col_config = {
        "Realm": 130,
        "AH Price": 90,
        "Qty": 60,
        "%Diff": 70
    }

    style = ttk.Style()
    style.theme_use("default")
    style.configure("Treeview",
                    background=accent_color,
                    foreground=fg_color,
                    rowheight=25,
                    fieldbackground=accent_color,
                    font=("Arial", 10))
    style.map("Treeview", background=[("selected", highlight_color)])

    style.configure("Treeview.Heading",
                    background=highlight_color,
                    foreground=fg_color,
                    font=("Arial", 10, "bold"))

    for col in columns:
        tree.heading(col, text=col, command=lambda _col=col: sort_treeview(tree, _col, False))
        tree.column(col, width=col_config[col], anchor="center", stretch=False)

    tree.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")

    tree.tag_configure("overpriced", foreground="red")
    tree.tag_configure("undercut", foreground="green")

    root.mainloop()

if __name__ == "__main__":
    main()
