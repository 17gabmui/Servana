#!/usr/bin/env python3
"""
Fetch Connected Realm index and details from Blizzard API and export to CSV (ID and realm names).

Usage:
  python fetch_connected_realms.py

Requires:
  • python-dotenv
  • requests

Outputs:
  • connected_realms.csv – CSV containing connected_realm_id and realm_names
"""
import os
import sys
import time
import csv
import requests
from dotenv import load_dotenv

# Load credentials
load_dotenv()
CLIENT_ID = os.getenv('BLIZZARD_CLIENT_ID')
CLIENT_SECRET = os.getenv('BLIZZARD_CLIENT_SECRET')
REGION = os.getenv('BLIZZARD_REGION', 'us')

# OAuth & API settings
TOKEN_URL = f"https://{REGION}.battle.net/oauth/token"
INDEX_URL = f"https://{REGION}.api.blizzard.com/data/wow/connected-realm/index"
DETAIL_URL = f"https://{REGION}.api.blizzard.com/data/wow/connected-realm/{{}}"
NAMESPACE = f"dynamic-{REGION}"
LOCALE = 'en_US'

_token = None
_token_expires = 0

def get_access_token():
    """Obtain a valid OAuth token, caching until expiry."""
    global _token, _token_expires
    now = time.time()
    if _token and now < _token_expires - 60:
        return _token
    resp = requests.post(
        TOKEN_URL,
        data={'grant_type': 'client_credentials'},
        auth=(CLIENT_ID, CLIENT_SECRET)
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data['access_token']
    _token_expires = now + data.get('expires_in', 0)
    return _token


def fetch_index():
    """Fetches the list of connected realm entries."""
    token = get_access_token()
    params = {'namespace': NAMESPACE, 'locale': LOCALE}
    headers = {'Authorization': f'Bearer {token}'}
    resp = requests.get(INDEX_URL, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json().get('connected_realms', [])


def fetch_detail(realm_id):
    """Fetches detailed info for a single connected realm by ID."""
    token = get_access_token()
    url = DETAIL_URL.format(realm_id)
    params = {'namespace': NAMESPACE, 'locale': LOCALE}
    headers = {'Authorization': f'Bearer {token}'}
    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit('Please set BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET in .env')

    entries = fetch_index()
    csv_file = 'connected_realms.csv'
    print(f"Writing {len(entries)} connected realms to {csv_file}...")

    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['connected_realm_id', 'realm_names'])

        for entry in entries:
            href = entry.get('key', {}).get('href') or entry.get('href', '')
            realm_id = href.rstrip('/').split('/')[-1].split('?')[0]

            # Fetch full detail to get realm names
            try:
                detail = fetch_detail(realm_id)
            except Exception as e:
                print(f"Error fetching details for {realm_id}: {e}")
                continue

            # Extract member realm names, handling both dict and string cases
            realms = detail.get('realms', [])
            names = []
            for r in realms:
                if isinstance(r, dict):
                    name_val = r.get('name')
                    if isinstance(name_val, dict):
                        names.append(name_val.get(LOCALE, ''))
                    else:
                        names.append(str(name_val))
                else:
                    names.append(str(r))

            writer.writerow([realm_id, ','.join(names)])

    print("CSV export complete.")

if __name__ == '__main__':
    main()
