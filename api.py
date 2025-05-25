#!/usr/bin/env python3
import time
import requests
import shelve
import threading
from auth import get_blizzard_token, get_tsm_token
from manage_realms_csv import load_selected_realms

# === Constants ===
TSM_REGION_ID     = 1
NAMESPACE         = "dynamic-us"
STATIC_NAMESPACE  = "static-us"
LOCALE            = "en_US"
TSM_CACHE         = "./.cache/tsm_cache.db"
NAME_CACHE        = "./.cache/item_name_cache.db"
PIC_CACHE         = "./.cache/item_pic_cache.db"
AUCTION_CACHE     = "./.cache/auction_cache.db"


def get_tsm_region_stats(item_id):
    """
    Fetch TSM marketValue and saleRate, caching results locally.
    """
    key = str(item_id)
    with shelve.open(TSM_CACHE) as db:
        if key in db:
            return db[key]

    token = get_tsm_token()
    if not token:
        return None, None

    try:
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
    except requests.exceptions.HTTPError:
        mv, sr = None, None

    with shelve.open(TSM_CACHE) as db:
        db[key] = (mv, sr)
    return mv, sr


def get_blizzard_name(item_id):
    """
    Fetch and cache the Blizzard item name (static namespace).
    """
    key = str(item_id)
    with shelve.open(NAME_CACHE) as db:
        if key in db:
            return db[key]

    token = get_blizzard_token()
    resp = requests.get(
        f"https://us.api.blizzard.com/data/wow/item/{item_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"namespace": STATIC_NAMESPACE, "locale": LOCALE}
    )
    resp.raise_for_status()
    name = resp.json().get("name", "Unknown Item")

    with shelve.open(NAME_CACHE) as db:
        db[key] = name
    return name


def get_blizzard_pic(item_id):
    """
    Fetch and cache the Blizzard item icon URL (static namespace).
    """
    key = str(item_id)
    with shelve.open(PIC_CACHE) as db:
        if key in db:
            return db[key]

    token = get_blizzard_token()
    resp = requests.get(
        f"https://us.api.blizzard.com/data/wow/media/item/{item_id}",
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


def get_realm_auctions(realm_id):
    """
    Fetch the raw auctions list for a connected realm from Blizzard API.
    """
    token = get_blizzard_token()
    url = f"https://us.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions"
    params = {"namespace": NAMESPACE, "locale": LOCALE}
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params
    )
    resp.raise_for_status()
    return resp.json()


def cache_realm_auctions(realm_id):
    """
    Fetch and store lowest buyout for each item in the given realm into local cache.
    """
    data = get_realm_auctions(realm_id)
    auctions = data.get("auctions", [])
    realm_key = str(realm_id)
    with shelve.open(AUCTION_CACHE) as db:
        realm_data = db.get(realm_key, {})
        for auc in auctions:
            item = auc.get("item", {}).get("id")
            buyout = auc.get("buyout")
            if item is not None and buyout is not None:
                existing = realm_data.get(str(item))
                realm_data[str(item)] = buyout if existing is None else min(existing, buyout)
        realm_data["_ts"] = time.time()
        db[realm_key] = realm_data
    return realm_data


def get_cached_auctions(realm_id):
    """
    Retrieve cached buyouts for a realm; returns dict of item_id->buyout.
    """
    with shelve.open(AUCTION_CACHE) as db:
        return db.get(str(realm_id), {})


def cache_selected_realms_auctions():
    """
    Cache auctions for all currently selected realms using threading.
    """
    realms = load_selected_realms()
    results = {}
    threads = []

    def worker(rid):
        results[rid] = cache_realm_auctions(rid)

    for rid in realms:
        t = threading.Thread(target=worker, args=(rid,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return results
