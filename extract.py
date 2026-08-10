import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LASTFM_API_KEY")
USERNAME = os.getenv("LASTFM_USERNAME")
BASE_URL = "https://ws.audioscrobbler.com/2.0/"

def fetch_page(page: int, limit: int = 200, from_ts: int | None = None):
    params = {
        "method": "user.getrecenttracks",
        "user": USERNAME,
        "api_key": API_KEY,
        "format": "json",
        "limit": limit,
        "page": page,
    }
    if from_ts:
        params["from"] = from_ts

    response = requests.get(BASE_URL, params=params)
    response.raise_for_status()
    return response.json()

def fetch_all_scrobbles(limit_per_page: int = 200, pause_seconds: float = 0.25, from_ts: int | None = None):
    all_tracks = []

    first_response = fetch_page(page=1, limit=limit_per_page, from_ts=from_ts)
    attrs = first_response["recenttracks"]["@attr"]
    total_pages = int(attrs["totalPages"])
    total_tracks = int(attrs["total"])

    print(f"Insgesamt {total_tracks} neue Tracks auf {total_pages} Pages")

    all_tracks.extend(first_response["recenttracks"]["track"])

    for page in range(2, total_pages + 1):
        print(f"Lade Page {page}/{total_pages}...")
        response = fetch_page(page=page, limit=limit_per_page, from_ts=from_ts)
        all_tracks.extend(response["recenttracks"]["track"])
        time.sleep(pause_seconds)

    return all_tracks

if __name__ == "__main__":
    tracks = fetch_all_scrobbles()
    print(f"\n{len(tracks)} Tracks insgesamt geladen")
    print("Beispiel-Track:", tracks[0])

    with open("raw_scrobbles.json", "w") as f:
        json.dump(tracks, f, indent=2)



