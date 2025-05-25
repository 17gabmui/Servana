import os
import time
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# OAuth token endpoints
BLIZZ_TOKEN_URL = "https://oauth.battle.net/token"
TSM_TOKEN_URL   = "https://auth.tradeskillmaster.com/oauth2/token"

# Caches for tokens
_cached_blizz = None
_blizz_expiry = 0
_cached_tsm   = None
_tsm_expiry   = 0

def get_blizzard_token():
    """
    Retrieve and cache a Blizzard API token using client credentials.
    """
    global _cached_blizz, _blizz_expiry
    now = time.time()
    if _cached_blizz and now < _blizz_expiry:
        return _cached_blizz
    resp = requests.post(
        BLIZZ_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(os.getenv("BLIZZARD_CLIENT_ID"), os.getenv("BLIZZARD_CLIENT_SECRET"))
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_blizz = data["access_token"]
    _blizz_expiry = now + data.get("expires_in", 1800) - 60
    return _cached_blizz

def get_tsm_token():
    """
    Retrieve and cache a TSM API token using API key.
    Falls back to None on errors.
    """
    global _cached_tsm, _tsm_expiry
    now = time.time()
    if _cached_tsm and now < _tsm_expiry:
        return _cached_tsm
    body = {
        "client_id": os.getenv("TSM_CLIENT_ID"),
        "grant_type": "api_token",
        "scope": "app:realm-api app:pricing-api",
        "token": os.getenv("TSM_API_KEY")
    }
    try:
        resp = requests.post(TSM_TOKEN_URL, json=body)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"TSM auth failed: {e}")
        return None
    data = resp.json()
    _cached_tsm = data.get("access_token")
    _tsm_expiry = now + data.get("expires_in", 3600) - 60
    return _cached_tsm
