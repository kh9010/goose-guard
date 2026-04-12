"""Basic tests for the Goose Guard sound agent and helpers.

Run from the project root:
    python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

# Ensure the project root is importable when running `python -m unittest`.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sound_agent import SoundAgent, DEFAULT_SAMPLE_RATE, MAX_KEPT_GENERATED  # noqa: E402
from system_info import format_uptime  # noqa: E402


class DummyEngine:
    """Stand-in for SoundEngine that just records rescans."""

    def __init__(self):
        self.scanned = 0

    def _scan_sounds(self):
        self.scanned += 1


class TestSoundAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sounds = Path(self.tmp.name) / "sounds"
        self.sounds.mkdir()
        self.engine = DummyEngine()
        self.agent = SoundAgent(self.sounds, self.engine)

    def tearDown(self):
        self.tmp.cleanup()

    def test_flavors_produce_valid_samples(self):
        flavors = [
            self.agent._flavor_chirp_sweep,
            self.agent._flavor_alarm_beeps,
            self.agent._flavor_noise_burst,
            self.agent._flavor_interval_pulse,
        ]
        for flavor in flavors:
            samples = flavor()
            self.assertGreater(len(samples), 1000,
                               f"{flavor.__name__} returned too few samples")
            for s in samples[:500]:
                self.assertGreaterEqual(s, -32768)
                self.assertLessEqual(s, 32767)

    def test_run_writes_valid_wav(self):
        path = self.agent.run()
        self.assertIsNotNone(path)
        wav_path = Path(path)
        self.assertTrue(wav_path.exists())
        self.assertEqual(self.engine.scanned, 1,
                         "engine should be rescanned after agent run")
        with wave.open(str(wav_path)) as w:
            self.assertEqual(w.getframerate(), DEFAULT_SAMPLE_RATE)
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertGreater(w.getnframes(), 0)

    def test_prune_enforces_cap(self):
        for _ in range(MAX_KEPT_GENERATED + 4):
            self.agent.run()
        agent_files = [
            f for f in (self.sounds / "generated").iterdir()
            if f.name.startswith("agent_") and f.suffix == ".wav"
        ]
        self.assertLessEqual(len(agent_files), MAX_KEPT_GENERATED)

    def test_has_generated_sounds_toggle(self):
        self.assertFalse(self.agent.has_generated_sounds())
        self.agent.run()
        self.assertTrue(self.agent.has_generated_sounds())

    def test_status_shape(self):
        self.agent.run()
        s = self.agent.status()
        self.assertIn("generated_count", s)
        self.assertIn("last_run", s)
        self.assertIn("files", s)
        self.assertIn("max_kept", s)
        self.assertIn("sources_file_present", s)
        self.assertGreaterEqual(s["generated_count"], 1)
        self.assertIsNotNone(s["last_run"])

    def test_fetch_from_sources_skips_when_missing(self):
        # No sound_sources.json → fetch is a no-op but must not raise.
        result = self.agent._fetch_from_sources()
        self.assertFalse(result)


class TestSystemInfo(unittest.TestCase):
    def test_format_uptime(self):
        self.assertEqual(format_uptime(0), "0s")
        self.assertEqual(format_uptime(30), "30s")
        self.assertEqual(format_uptime(90), "1m")
        self.assertEqual(format_uptime(3600), "1h 0m")
        self.assertEqual(format_uptime(3700), "1h 1m")
        self.assertEqual(format_uptime(90000), "1d 1h")

    def test_format_uptime_negative_clamps_to_zero(self):
        self.assertEqual(format_uptime(-10), "0s")


if __name__ == "__main__":
    unittest.main()
