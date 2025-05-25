#!/usr/bin/env python3
import time
import threading
import shelve
from api import get_realm_auctions
from manage_realms_csv import load_selected_realms

# Path to the auctions cache (shelf)
AUCTION_CACHE = "./.cache/auction_cache.db"


def get_cached_price(realm_id, item_id):
    """
    Return the cached lowest buyout price (int) for a given item in a realm, or None if missing.
    """
    key = str(realm_id)
    with shelve.open(AUCTION_CACHE) as db:
        realm_data = db.get(key, {})
    return realm_data.get(str(item_id))


def cache_realm_auctions(realm_id):
    """
    Fetch auction data for a single realm and update the cache with lowest buyouts.
    Returns the updated dict of item_id->buyout for that realm.
    """
    data = get_realm_auctions(realm_id)
    auctions = data.get("auctions", [])
    key = str(realm_id)
    with shelve.open(AUCTION_CACHE, writeback=True) as db:
        realm_data = db.get(key, {})
        for auc in auctions:
            item = auc.get('item', {}).get('id')
            buyout = auc.get('buyout')
            if item is None or buyout is None:
                continue
            item_key = str(item)
            existing = realm_data.get(item_key)
            realm_data[item_key] = buyout if existing is None else min(existing, buyout)
        realm_data['_ts'] = time.time()
        db[key] = realm_data
        return realm_data


def cache_selected_realms_auctions():
    """
    Cache auctions for all realms currently selected in manage_realms_csv, in parallel.
    Returns a dict mapping realm_id to its cached auction dict.
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


def get_cached_auctions(realm_id):
    """
    Get the entire cached auction dict (item_id->buyout) for a realm.
    """
    key = str(realm_id)
    with shelve.open(AUCTION_CACHE) as db:
        return db.get(key, {})
