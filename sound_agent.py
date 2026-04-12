"""
Sound agent for Goose Guard.

Runs on a weekly schedule and generates fresh procedural deterrent sounds
so the geese never hear exactly the same clips for long. Geese habituate
fast; the most important property of a deterrent sound is novelty, not
naturalness, which is why we can get away with synthesizing them locally
using only the stdlib.

Also supports optional downloads from sound_sources.json (a small file the
user can add with direct URLs to public-domain / CC0 audio). This is off
by default and never guesses URLs.
"""

import json
import math
import os
import random
import struct
import wave
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_SAMPLE_RATE = 22050
MAX_KEPT_GENERATED = 8        # trim old files so the SD card never fills
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10MB hard cap on fetched files


class SoundAgent:
    """Generates and curates fresh deterrent sounds."""

    def __init__(self, sounds_dir, sound_engine, log_callback=None):
        self.sounds_dir = Path(sounds_dir)
        self.sound_engine = sound_engine
        self.log_callback = log_callback or (lambda msg, src: None)
        # Agent-managed files live under their own category so we never
        # step on user-provided sounds.
        self.generated_dir = self.sounds_dir / "generated"
        self.sources_file = self.sounds_dir.parent / "sound_sources.json"

    # --- Public API ---

    def run(self):
        """Main entrypoint — generate a new sound and refresh the engine."""
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = self._generate_new_sound()
        except Exception as e:
            print(f"Sound agent generation failed: {e}")
            return None

        # Try the optional URL fetch; failures shouldn't break the run.
        try:
            self._fetch_from_sources()
        except Exception as e:
            print(f"Sound agent fetch failed: {e}")

        try:
            self._prune_old_generated()
        except Exception as e:
            print(f"Sound agent prune failed: {e}")

        # Let the engine see new/removed files immediately.
        if self.sound_engine is not None:
            try:
                self.sound_engine._scan_sounds()
            except Exception:
                pass

        if path:
            self.log_callback(os.path.basename(path), "agent")
        return path

    def has_generated_sounds(self):
        if not self.generated_dir.exists():
            return False
        for f in self.generated_dir.iterdir():
            if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".ogg"):
                return True
        return False

    def status(self):
        """Snapshot of the agent's state for the status page."""
        files = []
        if self.generated_dir.exists():
            entries = [
                f for f in self.generated_dir.iterdir()
                if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".ogg")
            ]
            entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            files = entries

        last_run = None
        if files:
            last_run = datetime.fromtimestamp(files[0].stat().st_mtime).isoformat(
                timespec="seconds"
            )

        return {
            "generated_count": len(files),
            "max_kept": MAX_KEPT_GENERATED,
            "last_run": last_run,
            "files": [f.name for f in files[:10]],
            "sources_file_present": self.sources_file.exists(),
        }

    # --- Flavors: each returns a list of 16-bit signed samples ---

    def _generate_new_sound(self):
        flavors = [
            self._flavor_chirp_sweep,
            self._flavor_alarm_beeps,
            self._flavor_noise_burst,
            self._flavor_interval_pulse,
        ]
        samples = random.choice(flavors)()
        suffix = random.randint(1000, 9999)
        filename = f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{suffix}.wav"
        path = self.generated_dir / filename
        self._write_wav(path, samples)
        return str(path)

    def _flavor_chirp_sweep(self):
        """Rising or falling siren sweep. Classic anti-bird chirp."""
        sr = DEFAULT_SAMPLE_RATE
        duration = random.uniform(0.8, 1.6)
        start_hz = random.randint(400, 900)
        end_hz = random.randint(2400, 3800)
        if random.random() < 0.5:
            start_hz, end_hz = end_hz, start_hz
        total = int(duration * sr)
        out = []
        for i in range(total):
            t = i / sr
            freq = start_hz + (end_hz - start_hz) * (i / total)
            sample = math.sin(2 * math.pi * freq * t)
            env = min(1.0, 8 * t, 8 * (duration - t))
            out.append(int(sample * env * 28000))
        return out

    def _flavor_alarm_beeps(self):
        """Short evenly-spaced beeps at a startled pitch."""
        sr = DEFAULT_SAMPLE_RATE
        beep_count = random.randint(4, 7)
        beep_ms = random.randint(80, 160)
        gap_ms = random.randint(60, 140)
        freq = random.randint(1500, 3200)
        samples_per_beep = int(sr * beep_ms / 1000)
        samples_per_gap = int(sr * gap_ms / 1000)
        out = []
        for _ in range(beep_count):
            for i in range(samples_per_beep):
                t = i / sr
                env = min(1.0, 12 * t, 12 * (beep_ms / 1000 - t))
                out.append(int(math.sin(2 * math.pi * freq * t) * env * 28000))
            out.extend([0] * samples_per_gap)
        return out

    def _flavor_noise_burst(self):
        """Warm shushy white-noise burst. Predator-rustling flavour."""
        sr = DEFAULT_SAMPLE_RATE
        duration = random.uniform(0.6, 1.2)
        total = int(duration * sr)
        alpha = random.uniform(0.12, 0.28)  # simple 1-pole lowpass
        prev = 0.0
        out = []
        for i in range(total):
            raw = random.uniform(-1.0, 1.0)
            prev = prev + alpha * (raw - prev)
            t = i / sr
            env = min(1.0, 6 * t, 6 * (duration - t))
            out.append(int(prev * env * 30000))
        return out

    def _flavor_interval_pulse(self):
        """Two-tone pulse like a car alarm."""
        sr = DEFAULT_SAMPLE_RATE
        pulse_ms = random.randint(150, 260)
        pulse_samples = int(sr * pulse_ms / 1000)
        hi = random.randint(1800, 2800)
        lo = random.randint(700, 1400)
        pulses = random.randint(3, 5)
        out = []
        for p in range(pulses):
            freq = hi if p % 2 == 0 else lo
            for i in range(pulse_samples):
                t = i / sr
                env = min(1.0, 10 * t, 10 * (pulse_ms / 1000 - t))
                out.append(int(math.sin(2 * math.pi * freq * t) * env * 27000))
            out.extend([0] * int(sr * 0.05))
        return out

    # --- IO ---

    def _write_wav(self, path, samples):
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(DEFAULT_SAMPLE_RATE)
            frames = b"".join(
                struct.pack("<h", max(-32768, min(32767, int(s)))) for s in samples
            )
            w.writeframes(frames)

    def _prune_old_generated(self):
        """Keep only the most recent MAX_KEPT_GENERATED agent files."""
        if not self.generated_dir.exists():
            return
        files = [
            f for f in self.generated_dir.iterdir()
            if f.is_file() and f.name.startswith("agent_")
            and f.suffix.lower() == ".wav"
        ]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[MAX_KEPT_GENERATED:]:
            try:
                old.unlink()
            except OSError:
                pass

    def _fetch_from_sources(self):
        """
        If the user has created a sound_sources.json alongside the project,
        try to download one new clip listed in it. The file format is:

            {"sources": [{"url": "https://...", "label": "..."}]}

        URLs must point directly at audio files. Downloads are capped at
        MAX_DOWNLOAD_BYTES and only accepted if the response looks like audio.
        """
        if not self.sources_file.exists():
            return False
        try:
            with open(self.sources_file) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False

        sources = data.get("sources", [])
        if not sources:
            return False

        existing = {p.name for p in self.generated_dir.iterdir() if p.is_file()}

        for src in random.sample(list(sources), len(sources)):
            url = src.get("url")
            if not url:
                continue
            basename = os.path.basename(urlparse(url).path)
            if not basename or basename in existing:
                continue
            if not basename.lower().endswith((".mp3", ".wav", ".ogg")):
                continue
            try:
                req = Request(url, headers={"User-Agent": "GooseGuard/1.0"})
                with urlopen(req, timeout=15) as resp:
                    if getattr(resp, "status", 200) != 200:
                        continue
                    content_type = resp.headers.get("Content-Type", "") or ""
                    if "audio" not in content_type.lower() and \
                            not basename.lower().endswith((".mp3", ".wav", ".ogg")):
                        continue
                    body = resp.read(MAX_DOWNLOAD_BYTES)
                target = self.generated_dir / basename
                with open(target, "wb") as f:
                    f.write(body)
                return True
            except Exception as e:
                print(f"Sound source fetch failed for {url}: {e}")
                continue
        return False
