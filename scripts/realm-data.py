import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
CLIENT_ID = os.getenv('BLIZZARD_CLIENT_ID')
CLIENT_SECRET = os.getenv('BLIZZARD_CLIENT_SECRET')
REGION = os.getenv('BLIZZARD_REGION', 'us')
LOCALE = 'en_US'

# Target realms (slug format)
TARGET_REALMS = [
    "area-52", "bleeding-hollow", "thrall",
    "zuljin", "sargeras", "malganis", "illidan", "tichondrius"
]

def get_access_token():
    url = f"https://{REGION}.battle.net/oauth/token"
    response = requests.post(url, data={'grant_type': 'client_credentials'}, auth=(CLIENT_ID, CLIENT_SECRET))
    response.raise_for_status()
    return response.json()['access_token']

def get_realm_data(token, slug):
    url = f"https://{REGION}.api.blizzard.com/data/wow/realm/{slug}?namespace=dynamic-{REGION}&locale={LOCALE}"
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_connected_realm_data(token, connected_realm_url):
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(f"{connected_realm_url}&locale={LOCALE}", headers=headers)
    response.raise_for_status()
    return response.json()

def main():
    token = get_access_token()
    seen_urls = set()

    for slug in TARGET_REALMS:
        print(f"Looking up realm: {slug}")
        try:
            # Get individual realm data (this gives the correct realm ID)
            realm_data = get_realm_data(token, slug)
            realm_id = realm_data['id']
            realm_name = realm_data['name']
            connected_url = realm_data['connected_realm']['href']

            if connected_url in seen_urls:
                print("  Skipping duplicate connected realm.")
                continue
            seen_urls.add(connected_url)

            connected_data = get_connected_realm_data(token, connected_url)
            region = connected_data['realms'][0].get('region', {}).get('name', 'Unknown')
            timezone = connected_data.get('timezone', 'Unknown')
            population = connected_data.get('population', {}).get('type', 'Unknown')
            status = 'Online' if connected_data.get('status', {}).get('type') == 'UP' else 'Offline'

            print(f"{realm_name} (Realm ID: {realm_id})")
            print(f"  Region: {region}")
            print(f"  Timezone: {timezone}")
            print(f"  Population: {population}")
            print(f"  Status: {status}")
            print("-" * 40)

        except Exception as e:
            print(f"  Error for realm '{slug}': {e}")

if __name__ == '__main__':
    main()
