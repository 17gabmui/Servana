#!/usr/bin/env python3
"""
Servana CLI – Auction Data Fetcher with Name & Image Caching

Part of the Servana WoW AH Price Checker suite. This script:
  • Fetches raw auction data for a specified connected-realm (default 4)
  • Caches all unique item names to `item_name_cache.db`
  • Caches all unique item icon URLs to `item_pic_cache.db`
  • Writes the full auction JSON to a file

Usage:
  servana --realm <ID>

Requires:
  • python-dotenv
  • requests

Outputs:
  • auctions_<realm>_raw.json      – full auction list
  • item_name_cache.db             – shelve of item IDs → names
  • item_pic_cache.db              – shelve of item IDs → icon URLs
"""

import os
import time
import argparse
import json
import requests
import shelve
from dotenv import load_dotenv

# Load environment variables from .env or system
load_dotenv()

# OAuth & API endpoints
TOKEN_URL = "https://us.battle.net/oauth/token"
BASE_API  = "https://us.api.blizzard.com/data/wow"

# Cache filenames
NAME_CACHE = "item_name_cache.db"
PIC_CACHE  = "item_pic_cache.db"

# Token cache
_cached_token = None
_token_expiry  = 0.0


def fetch_token(client_id: str, client_secret: str) -> None:
    """Fetch and cache a new Blizzard OAuth token."""
    global _cached_token, _token_expiry
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret)
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_token = data["access_token"]
    _token_expiry = time.time() + data["expires_in"]
    print(f"[token] fetched new token; expires in {data['expires_in']}s")


def get_token(client_id: str, client_secret: str) -> str:
    """Return a valid Bearer token, refreshing if near expiry."""
    global _cached_token, _token_expiry
    if _cached_token is None or time.time() > (_token_expiry - 300):
        fetch_token(client_id, client_secret)
    return _cached_token


def fetch_raw_auctions(realm_id: int, client_id: str, client_secret: str) -> dict:
    """Fetch full JSON auctions for a connected-realm."""
    token = get_token(client_id, client_secret)
    url = f"{BASE_API}/connected-realm/{realm_id}/auctions"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"namespace": "dynamic-us", "locale": "en_US"}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def cache_names_and_pics(item_ids: set, client_id: str, client_secret: str) -> None:
    """
    Fetch and cache names and icon URLs for each unique item ID,
    calling `.sync()` immediately after each write to flush the shelf.
    """
    token = get_token(client_id, client_secret)
    name_new = 0
    pic_new  = 0

    # Open both shelves and keep them around for syncing
    with shelve.open(NAME_CACHE) as name_db, shelve.open(PIC_CACHE) as pic_db:
        for item_id in item_ids:
            key = str(item_id)

            # Cache name + sync
            if key not in name_db:
                try:
                    name_url = f"{BASE_API}/item/{item_id}"
                    resp = requests.get(
                        name_url,
                        headers={"Authorization": f"Bearer {token}"},
                        params={"namespace": "static-us", "locale": "en_US"}
                    )
                    resp.raise_for_status()
                    name = resp.json().get("name", "Unknown Item")

                    name_db[key] = name
                    name_db.sync()              # ← flush name immediately
                    name_new += 1
                except requests.HTTPError as e:
                    print(f"[name-cache] failed for {item_id}: {e}")

            # Cache icon URL + sync
            if key not in pic_db:
                try:
                    pic_url = f"{BASE_API}/media/item/{item_id}"
                    resp = requests.get(
                        pic_url,
                        headers={"Authorization": f"Bearer {token}"},
                        params={"namespace": "static-us", "locale": "en_US"}
                    )
                    resp.raise_for_status()
                    assets = resp.json().get("assets", [])
                    icon = next((a.get("value") for a in assets if a.get("key") == "icon"), None)

                    if icon:
                        pic_db[key] = icon
                        pic_db.sync()           # ← flush pic immediately
                        pic_new += 1
                except requests.HTTPError as e:
                    print(f"[pic-cache] failed for {item_id}: {e}")

        # Compute totals while shelves are still open
        total_names = len(name_db)
        total_pics  = len(pic_db)

    # Shelves auto-close here
    print(f"[cache] cached {name_new} new names, {pic_new} new icons; "
          f"total names={total_names}, total icons={total_pics}")


def save_json(data: dict, realm_id: int) -> None:
    """Write raw JSON to auctions_<realm>_raw.json."""
    fn = f"auctions_{realm_id}_raw.json"
    with open(fn, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"[json] saved raw data to {fn}")


def main():
    # Credentials from environment
    client_id     = os.getenv("BLIZZARD_CLIENT_ID")
    client_secret = os.getenv("BLIZZARD_CLIENT_SECRET")
    if not (client_id and client_secret):
        print("Error: set BLIZZARD_CLIENT_ID & BLIZZARD_CLIENT_SECRET in environment or .env")
        exit(1)

    parser = argparse.ArgumentParser(prog="servana",
                                     description="Fetch auctions & cache item names/pics")
    parser.add_argument('--realm', '-r', type=int, default=4,
                        help='Connected-realm ID (default: 4)')
    args = parser.parse_args()

    try:
        data = fetch_raw_auctions(args.realm, client_id, client_secret)
        save_json(data, args.realm)
        ids = {a['item']['id'] for a in data.get('auctions', [])}
        cache_names_and_pics(ids, client_id, client_secret)
    except requests.HTTPError as e:
        print(f"HTTP {e.response.status_code}: {e.response.text}")
        exit(1)


if __name__ == '__main__':
    main()
