#!/usr/bin/env python3
"""
Servana Blizzard AH Raw Data Fetcher

Fetches raw auction data for a given connected-realm ID using Blizzard's OAuth2,
and writes the complete JSON response to a file.
"""

import os
import time
import argparse
import json
import requests
from dotenv import load_dotenv

# Blizzard OAuth & API endpoints
TOKEN_URL = "https://us.battle.net/oauth/token"
BASE_API  = "https://us.api.blizzard.com/data/wow"

# Globals for caching the token
_cached_token = None
_token_expiry = 0.0


def fetch_token(client_id: str, client_secret: str) -> None:
    """
    Fetch a new OAuth token and update the global cache.
    """
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
    print(f"[token] fetched new token, expires in {data['expires_in']:,}s")


def get_token(client_id: str, client_secret: str) -> str:
    """
    Return a valid Bearer token, refreshing it if it's close to expiry.
    """
    if _cached_token is None or time.time() > (_token_expiry - 300):
        fetch_token(client_id, client_secret)
    return _cached_token


def get_raw_auctions(realm_id: int, client_id: str, client_secret: str) -> dict:
    """
    Fetch the full JSON response for the given connected-realm ID.
    """
    token = get_token(client_id, client_secret)
    url = f"{BASE_API}/connected-realm/{realm_id}/auctions"
    headers = {"Authorization": f"Bearer {token}"}
    params  = {"namespace": "dynamic-us", "locale": "en_US"}

    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def write_raw_json(data: dict, realm_id: int) -> None:
    """
    Write the complete JSON response to a file.
    """
    filename = f"auctions_{realm_id}_raw.json"
    with open(filename, mode="w") as f:
        json.dump(data, f, indent=2)
    print(f"[json] Wrote raw data to {filename}")


def main():
    load_dotenv()  # loads BLIZZARD_CLIENT_ID / SECRET from .env

    client_id     = os.getenv("BLIZZARD_CLIENT_ID")
    client_secret = os.getenv("BLIZZARD_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Error: set BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET in the environment.")
        return

    parser = argparse.ArgumentParser(
        description="Fetch raw WoW connected-realm auctions JSON from Blizzard."
    )
    parser.add_argument(
        "--realm", "-r",
        type=int,
        default=4,
        help="Connected-realm ID to fetch (default: 4)"
    )
    args = parser.parse_args()

    try:
        data = get_raw_auctions(args.realm, client_id, client_secret)
    except requests.HTTPError as e:
        print(f"HTTP error: {e.response.status_code} – {e.response.text}")
        return

    write_raw_json(data, args.realm)


if __name__ == "__main__":
    main()
