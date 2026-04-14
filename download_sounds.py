"""
download_sounds.py — Fetch free bird deterrent sounds for Goose Guard.

Uses verified recordings from:
  - Hamilton Naturalists' Club bioacoustic collection (CC BY 4.0)
  - Red Library Animals & Birds collection (CC0 public domain)

All files are short (4-30 seconds) real field recordings.

Run with:  python download_sounds.py
"""

import urllib.request
from pathlib import Path

SOUNDS_DIR = Path(__file__).parent / "sounds"

# Verified, real bird call recordings — all under 700KB
SOUNDS = {
    "predator": [
        ("red_tailed_hawk_1.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-3928/hamont-bioacoustic-observation-3928.mp3"),
        ("red_tailed_hawk_2.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-3920/hamont-bioacoustic-observation-3920.mp3"),
        ("red_tailed_hawk_3.mp3",
         "https://archive.org/download/Red_Library_Animals_Birds/R30-34-Red%20Tailed%20Hawk.mp3"),
        ("great_horned_owl_1.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-2200/hamont-bioacoustic-observation-2200.mp3"),
        ("great_horned_owl_2.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-2204/hamont-bioacoustic-observation-2204.mp3"),
        ("great_horned_owl_3.mp3",
         "https://archive.org/download/Red_Library_Animals_Birds/R01-27-Great%20Horned%20Owl%20Hoot.mp3"),
    ],
    "distress": [
        ("crow_alarm_1.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-1026/hamont-bioacoustic-observation-1026.mp3"),
        ("crow_alarm_2.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-1612/hamont-bioacoustic-observation-1612.mp3"),
        ("crow_alarm_3.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-1709/hamont-bioacoustic-observation-1709.mp3"),
        ("ducks_quacking.mp3",
         "https://archive.org/download/Red_Library_Animals_Birds/R30-32-Ducks%20Quack%20on%20Pond.mp3"),
    ],
    "startle": [
        ("blue_jay_alarm_1.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-3525/hamont-bioacoustic-observation-3525.mp3"),
        ("blue_jay_alarm_2.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-1813/hamont-bioacoustic-observation-1813.mp3"),
        ("blue_jay_alarm_3.mp3",
         "https://archive.org/download/ecolore-hamont-bioacoustic-observation-2034/hamont-bioacoustic-observation-2034.mp3"),
    ],
}


def download_file(url, dest_path):
    req = urllib.request.Request(url, headers={"User-Agent": "GooseGuard/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)


def main():
    print("=" * 55)
    print("  Goose Guard — Sound Downloader")
    print("  Sources: Hamilton Naturalists Club + Red Library")
    print("           (CC-licensed real field recordings)")
    print("=" * 55)

    total = 0
    skipped = 0

    for category, files in SOUNDS.items():
        folder = SOUNDS_DIR / category
        folder.mkdir(parents=True, exist_ok=True)
        print(f"\n[{category}]")

        for filename, url in files:
            dest = folder / filename
            if dest.exists() and dest.stat().st_size > 1000:
                print(f"  Already have: {filename}")
                skipped += 1
                continue

            print(f"  Downloading: {filename}...", end=" ", flush=True)
            try:
                download_file(url, dest)
                size_kb = dest.stat().st_size // 1024
                if size_kb < 1:
                    dest.unlink()
                    print("skipped (empty response)")
                    continue
                print(f"done ({size_kb} KB)")
                total += 1
            except Exception as e:
                print(f"failed — {e}")
                if dest.exists():
                    dest.unlink()

    print("\n" + "=" * 55)
    print(f"  Downloaded {total} new files, {skipped} already present.")
    print(f"  Location: {SOUNDS_DIR}")
    print("=" * 55)


if __name__ == "__main__":
    main()
