#!/usr/bin/env python3
"""
Dump all Blizzard connected-realm auctions to CSV by brute-force ID scan.

Writes ./connected_realms.csv with columns:
  connected_realm_id,realm_id,realm_name
"""
import os
import time
import csv
import requests
from dotenv import load_dotenv

# --- CONFIG ---
REGION      = os.getenv("BLIZZARD_REGION", "us")
NAMESPACE   = f"dynamic-{REGION}"
LOCALE      = "en_US"
OUTPUT_CSV  = "connected_realms.csv"
MAX_ID      = 5000        # bump this ceiling if needed
DELAY       = 0.1         # seconds between requests to be polite

# OAuth
load_dotenv()
CLIENT_ID     = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")
if not CLIENT_ID or not CLIENT_SECRET:
    raise SystemExit("BLIZZARD_CLIENT_ID/SECRET must be in .env")

_token      = None
_token_exp  = 0
def get_token():
    global _token, _token_exp
    now = time.time()
    if _token and now < _token_exp:
        return _token
    resp = requests.post(
        f"https://{REGION}.battle.net/oauth/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type":"client_credentials"}
    )
    resp.raise_for_status()
    j = resp.json()
    _token     = j["access_token"]
    _token_exp = now + j.get("expires_in",1800) - 60
    return _token

# Main
def main():
    url_tpl = (
        f"https://{REGION}.api.blizzard.com/data/wow/connected-realm/"
        "{{cr_id}}?namespace=" + NAMESPACE + "&locale=" + LOCALE
    )

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["connected_realm_id", "realm_id", "realm_name"])

        for cr_id in range(1, MAX_ID+1):
            time.sleep(DELAY)
            token = get_token()
            url = url_tpl.format(cr_id=cr_id)
            r = requests.get(url, headers={"Authorization":f"Bearer {token}"})
            if r.status_code == 404:
                continue
            try:
                r.raise_for_status()
                data = r.json()
                for realm in data.get("realms", []):
                    writer.writerow([cr_id, realm["id"], realm.get("name","")])
                print(f"OK: connected-realm {cr_id} → {len(data.get('realms',[]))} realms")
            except Exception as e:
                # skip any other error
                print(f"Skipping {cr_id}: {e}")

    print(f"Done. See {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
