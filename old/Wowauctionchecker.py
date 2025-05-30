import requests
import os
import time
from dotenv import load_dotenv
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk  # <-- Added for logo

# Load environment variables
load_dotenv()

# Blizzard and TSM credentials
BLIZZARD_CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
BLIZZARD_CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")
TSM_CLIENT_ID = os.getenv("TSM_CLIENT_ID")
TSM_API_KEY = os.getenv("TSM_API_KEY")

# Token cache
cached_tsm_token = None
cached_tsm_token_expiry = 0

# Constants
BLIZZ_TOKEN_URL = "https://oauth.battle.net/token"
BLIZZ_AH_URL = "https://us.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions"
TSM_TOKEN_URL = "https://auth.tradeskillmaster.com/oauth2/token"
TSM_REGION_ID = 1
NAMESPACE = "dynamic-us"
LOCALE = "en_US"

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
    response = requests.post(
        BLIZZ_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(BLIZZARD_CLIENT_ID, BLIZZARD_CLIENT_SECRET)
    )
    response.raise_for_status()
    return response.json()["access_token"]

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

    headers = {"Content-Type": "application/json"}
    response = requests.post(TSM_TOKEN_URL, json=data, headers=headers)
    response.raise_for_status()

    result = response.json()
    cached_tsm_token = result["access_token"]
    cached_tsm_token_expiry = time.time() + result.get("expires_in", 3600) - 60

    return cached_tsm_token

def get_tsm_region_stats(item_id, region_id=TSM_REGION_ID):
    access_token = get_tsm_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://pricing-api.tradeskillmaster.com/region/{region_id}/item/{item_id}"
    response = requests.get(url, headers=headers)
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    data = response.json()
    return data.get("marketValue"), data.get("saleRate")

def get_blizzard_price(realm_id, item_id, token):
    url = BLIZZ_AH_URL.format(realm_id=realm_id)
    headers = {"Authorization": f"Bearer {token}"}
    params = {"namespace": NAMESPACE, "locale": LOCALE}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    auctions = response.json().get("auctions", [])
    matches = [a.get("unit_price") or a.get("buyout") for a in auctions if a["item"]["id"] == item_id]
    quantity = sum(a.get("quantity", 0) for a in auctions if a["item"]["id"] == item_id)
    return (min(matches) if matches else None), quantity

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

def run_query(item_id_str, tree, item_label, sale_rate_label):
    tree.delete(*tree.get_children())
    try:
        item_id = int(item_id_str.strip())
    except ValueError:
        messagebox.showerror("Error", "Invalid item ID")
        return

    try:
        blizz_token = get_blizzard_token()
        tsm_region_price, tsm_sale_rate = get_tsm_region_stats(item_id)
        item_label.config(text=f"Item ID: {item_id}")
        sale_rate_label.config(text=f"Sale Rate: {tsm_sale_rate:.1%}" if tsm_sale_rate else "Sale Rate: —")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to authenticate or get TSM price: {e}")
        return

    for realm_id, realm_name in REALMS.items():
        try:
            blizz_price, quantity = get_blizzard_price(realm_id, item_id, blizz_token)
            percent_diff = "—"
            tag = ""

            if blizz_price is not None and tsm_region_price and tsm_region_price != 0:
                diff = (blizz_price - tsm_region_price) / tsm_region_price * 100
                percent_diff = f"{diff:+.1f}%"
                tag = "overpriced" if diff > 0 else "undercut" if diff < 0 else ""

            tree.insert("", "end", values=(
                realm_name,
                format_price(blizz_price),
                quantity,
                percent_diff
            ), tags=(tag,))
        except Exception:
            tree.insert("", "end", values=(realm_name, "Error", 0, "—"))

def main():
    root = tk.Tk()
    root.title("Servana - WoW Auction Price Checker")
    root.geometry("400x500")
    root.resizable(False, False)

    # === CENTERED INPUT + LOGO BUTTON ===
    frm_input = tk.Frame(root)
    frm_input.pack(pady=10)

    entry = tk.Entry(frm_input, font=("Arial", 12), width=30, justify="center")
    entry.pack(pady=5)

    try:
        logo_button_img = Image.open("assets/servana_logo.png")
        resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
        logo_button_img = logo_button_img.resize((250, 80), resample=resample_filter)
        logo_button_photo = ImageTk.PhotoImage(logo_button_img)

        btn_logo = tk.Button(
            frm_input, image=logo_button_photo,
            command=lambda: run_query(entry.get(), tree, item_label, sale_rate_label),
            borderwidth=0, highlightthickness=0, cursor="hand2", bg="white", activebackground="white"
        )
        btn_logo.image = logo_button_photo
        btn_logo.pack(pady=(0, 5))
    except Exception as e:
        print(f"Could not load logo search button: {e}")
        btn = tk.Button(frm_input, text="Search", command=lambda: run_query(entry.get(), tree, item_label, sale_rate_label))
        btn.pack()

    # === INFO LABELS ===
    label_frame = tk.Frame(frm_input)
    label_frame.pack(fill="x", padx=20)

    item_label = tk.Label(label_frame, text="Item: ", font=("Arial", 10, "bold"))
    item_label.pack(side="left")

    sale_rate_label = tk.Label(label_frame, text="Sale Rate: —", font=("Arial", 10, "italic"))
    sale_rate_label.pack(side="right")

    # === AUCTION DATA TABLE ===
    columns = ("Realm", "AH Price", "Qty", "%Diff")
    tree = ttk.Treeview(root, columns=columns, show="headings")

    col_config = {
        "Realm": 130,
        "AH Price": 90,
        "Qty": 60,
        "%Diff": 70
    }

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
