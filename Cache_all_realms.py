#!/usr/bin/env python3
"""
Fetch all WoW realms automatically and cache their full JSON data in a local shelve database.

Usage:
  python cache_all_realms.py

Requires:
  • python-dotenv
  • requests
"""
import os
import sys
import time
import requests
import shelve
from dotenv import load_dotenv

# Load credentials
script_dir = os.path.dirname(__file__)
load_dotenv(os.path.join(script_dir, '.env'))
BLIZZ_CLIENT_ID     = os.getenv('BLIZZARD_CLIENT_ID')
BLIZZ_CLIENT_SECRET = os.getenv('BLIZZARD_CLIENT_SECRET')
REGION              = os.getenv('BLIZZARD_REGION', 'us')

if not BLIZZ_CLIENT_ID or not BLIZZ_CLIENT_SECRET:
    sys.exit('Error: BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET must be set in .env')

# Endpoints
OAUTH_URL      = f'https://{REGION}.battle.net/oauth/token'
REALM_INDEX_URL = f'https://{REGION}.api.blizzard.com/data/wow/realm/index'
REALM_URL      = f'https://{REGION}.api.blizzard.com/data/wow/realm/{{slug}}'

# Cache directory and DB
CACHE_DIR = os.path.join(script_dir, '.cache')
os.makedirs(CACHE_DIR, exist_ok=True)
DB_PATH = os.path.join(CACHE_DIR, 'realms_cache.db')

# Token cache
o_blizz_token = None
_blizz_expiry  = 0

# Obtain Blizzard OAuth token
def get_blizz_token():
    global o_blizz_token, _blizz_expiry
    now = time.time()
    if o_blizz_token and now < _blizz_expiry:
        return o_blizz_token
    resp = requests.post(
        OAUTH_URL,
        data={'grant_type': 'client_credentials'},
        auth=(BLIZZ_CLIENT_ID, BLIZZ_CLIENT_SECRET)
    )
    resp.raise_for_status()
    data = resp.json()
    o_blizz_token = data['access_token']
    _blizz_expiry = now + data.get('expires_in', 1800) - 60
    return o_blizz_token

# Fetch all realm slugs from index
def fetch_all_slugs():
    token = get_blizz_token()
    headers = {'Authorization': f'Bearer {token}'}
    params = {'namespace': f'dynamic-{REGION}', 'locale': 'en_US'}
    resp = requests.get(REALM_INDEX_URL, headers=headers, params=params)
    resp.raise_for_status()
    items = resp.json().get('realms', [])
    slugs = []
    for entry in items:
        href = entry.get('key', {}).get('href', '')
        slug = href.rstrip('/').split('/')[-1]
        if slug:
            slugs.append(slug)
    return slugs

# Fetch full realm data by slug
def fetch_realm_data(slug):
    token = get_blizz_token()
    url = REALM_URL.format(slug=slug)
    headers = {'Authorization': f'Bearer {token}'}
    params = {'namespace': f'dynamic-{REGION}', 'locale': 'en_US'}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()

# Main caching process
def main():
    print('Fetching all realm slugs...')
    slugs = fetch_all_slugs()
    print(f'Found {len(slugs)} realms, caching full data...')

    with shelve.open(DB_PATH) as db:
        for slug in slugs:
            try:
                data = fetch_realm_data(slug)
                realm_id = str(data.get('id'))
                db[realm_id] = data
            except Exception as e:
                print(f"Failed to cache {slug}: {e}", file=sys.stderr)

    print(f'Cached {len(db)} realms to {DB_PATH}')

if __name__ == '__main__':
    main()
