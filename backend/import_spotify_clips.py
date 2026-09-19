import json
import os
import requests
import time
from pathlib import Path
from spotify_oauth_service import SpotifyOAuthService

# Ensure you have your Spotify credentials in your environment variables
# SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, and a valid access token.

DATA_DIR = Path(__file__).parent / "data"
CLIPS_DIR = DATA_DIR / "clips"
CLIPS_DIR.mkdir(parents=True, exist_ok=True)
FEATURES_PATH = DATA_DIR / "clip_features.json"

def search_spotify_for_preview(token, query):
    res = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": query, "type": "track", "limit": 10},
        timeout=5
    )
    if res.status_code == 200:
        tracks = res.json().get("tracks", {}).get("items", [])
        for t in tracks:
            if t.get("preview_url"):
                return t
    return None

def main(access_token):
    if not FEATURES_PATH.exists():
        print(f"Error: {FEATURES_PATH} not found.")
        return

    with open(FEATURES_PATH, "r", encoding="utf-8") as f:
        clip_features = json.load(f)

    print(f"Loaded {len(clip_features)} clips for import.")

    for clip_id, data in clip_features.items():
        genre_hint = data.get("genre_hint", "")
        title_hint = data.get("title", "")
        print(f"Searching Spotify for: {title_hint} ({genre_hint})...")
        
        # Build a search query
        query = f"{genre_hint} {title_hint}"
        track = search_spotify_for_preview(access_token, query)
        
        if track:
            preview_url = track["preview_url"]
            print(f"  Found track: {track['name']} by {track['artists'][0]['name']}")
            print(f"  Downloading preview: {preview_url}")
            
            audio_res = requests.get(preview_url)
            if audio_res.status_code == 200:
                filename = f"{clip_id}.mp3"
                filepath = CLIPS_DIR / filename
                with open(filepath, "wb") as f_out:
                    f_out.write(audio_res.content)
                
                # Update JSON
                clip_features[clip_id]["audio_url"] = f"/assets/clips/{filename}"
                clip_features[clip_id]["spotify_uri"] = track["uri"]
                clip_features[clip_id]["spotify_id"] = track["id"]
                print(f"  Saved {filename}.")
            else:
                print(f"  Failed to download audio for {clip_id}")
        else:
            print(f"  No preview found for {clip_id}.")
        
        time.sleep(1) # Rate limit

    with open(FEATURES_PATH, "w", encoding="utf-8") as f:
        json.dump(clip_features, f, indent=2)
    print("Updated clip_features.json!")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python import_spotify_clips.py <SPOTIFY_ACCESS_TOKEN>")
        sys.exit(1)
    main(sys.argv[1])
