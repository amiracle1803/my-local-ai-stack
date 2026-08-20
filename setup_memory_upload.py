#!/usr/bin/env python3
"""
Upload docs to TencentDB Agent Memory Hub Wiki
Cross-platform: works on Linux, Windows, macOS
"""
import os
import sys
import requests
from pathlib import Path

# === CONFIGURATION ===
BASE_URL = "http://localhost:8424/v3"
TEAM_ID = "team-6ef2zvnu7i"
# API key is read from the MEMORY_API_KEY env var (set in the gitignored .env).
# Never hardcode the token in this tracked file.
API_KEY = os.environ.get("MEMORY_API_KEY", "")
if not API_KEY:
    raise SystemExit("MEMORY_API_KEY is not set (see .env).")
WIKI_ID = "wiki-rgmz1nsf"  # Already created

# === FILE MAPPING ===
ROOT = Path(__file__).parent

FILES_TO_UPLOAD = [
    ("AGENTS.md", ROOT / "AGENTS.md"),
    ("README.md", ROOT / "README.md"),
    ("GUIDE.md", ROOT / "docs" / "GUIDE.md"),
    ("TROUBLESHOOTING.md", ROOT / "docs" / "TROUBLESHOOTING.md"),
    ("stack.toml", ROOT / "stack.toml"),
]

HEADERS = {
    "x-tdai-user-key": API_KEY,
    "x-tdai-service-id": "default"
}

def upload_file(filename, file_path):
    if not file_path.exists():
        print(f"⚠️  File not found: {file_path}")
        return False

    # Use raw/write endpoint (works for multiple files)
    url = f"{BASE_URL}/wiki/raw/write"
    payload = {
        "team_id": TEAM_ID,
        "wiki_id": WIKI_ID,
        "files": [{"filename": filename, "content": file_path.read_text(encoding='utf-8')}]
    }
    
    try:
        print(f"📤 Uploading: {filename} ({file_path.stat().st_size} bytes)")
        resp = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"})
        if resp.status_code == 200:
            print(f"✅ Success: {filename}")
            return True
        else:
            print(f"❌ Failed: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Error uploading {filename}: {e}")
        return False

def ingest_wiki():
    """Trigger wiki ingestion to make content searchable"""
    url = f"{BASE_URL}/wiki/ingest"
    payload = {"wiki_id": WIKI_ID}
    try:
        print(f"🔄 Starting wiki ingestion...")
        resp = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"})
        if resp.status_code == 200:
            print(f"✅ Ingestion started: {resp.json()}")
            return True
        else:
            print(f"❌ Ingestion failed: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Error starting ingestion: {e}")
        return False

def main():
    print("🚀 Starting memory upload process...")
    print(f"   Team: {TEAM_ID}")
    print(f"   Wiki: {WIKI_ID}")
    print(f"   Base URL: {BASE_URL}")
    print()
    
    uploaded = 0
    for filename, path in FILES_TO_UPLOAD:
        if upload_file(filename, path):
            uploaded += 1
    
    print(f"\n📊 Uploaded {uploaded}/{len(FILES_TO_UPLOAD)} files.")
    
    if uploaded > 0:
        print()
        ingest_wiki()
    
    print("\n🎉 Done!")

if __name__ == "__main__":
    main()
