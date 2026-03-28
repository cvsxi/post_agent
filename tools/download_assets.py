from __future__ import annotations

from pathlib import Path
import json
import time
import urllib.request


def fetch_binary(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "post-agent-bot/0.1 (local image downloader)"
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    manifest_path = base_dir / "content" / "images" / "manifest.json"
    images_dir = base_dir / "content" / "images"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for item in manifest["images"]:
        destination = images_dir / item["file"]
        if destination.exists():
            print(f"skip {destination.name}: already exists")
            continue

        image_url = item["download_url"]
        try:
            binary = fetch_binary(image_url)
            destination.write_bytes(binary)
            print(f"saved {destination.name}")
        except Exception as error:
            print(f"failed {destination.name}: {error}")
        time.sleep(2)


if __name__ == "__main__":
    main()
