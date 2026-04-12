"""
Sound engine for Goose Guard.
Handles audio playback, sound indexing, anti-habituation logic, and volume control.
"""

import os
import random
import threading
import time
from collections import deque
from pathlib import Path

import pygame


class SoundEngine:
    def __init__(self, sounds_dir="sounds"):
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        self.sounds_dir = Path(sounds_dir)
        self.sounds = {}  # category -> list of file paths
        self.recently_played = deque(maxlen=15)
        self.current_sound = None
        self.playing = False
        self.volume = 85
        self._lock = threading.Lock()
        self._scan_sounds()

    def _scan_sounds(self):
        """Scan the sounds directory and index all audio files by category."""
        self.sounds = {}
        if not self.sounds_dir.exists():
            return
        for category_dir in self.sounds_dir.iterdir():
            if category_dir.is_dir():
                category = category_dir.name
                files = sorted([
                    str(f) for f in category_dir.iterdir()
                    if f.suffix.lower() in (".mp3", ".wav", ".ogg")
                ])
                if files:
                    self.sounds[category] = files

    def get_sounds(self):
        """Return all sounds organized by category."""
        self._scan_sounds()
        result = {}
        for category, files in self.sounds.items():
            result[category] = [os.path.basename(f) for f in files]
        return result

    def get_all_files(self):
        """Return a flat list of all sound file paths."""
        all_files = []
        for files in self.sounds.values():
            all_files.extend(files)
        return all_files

    def _pick_sound(self, category=None, specific_file=None):
        """
        Pick a sound to play using the anti-habituation algorithm.
        - If specific_file is given, play that exact file.
        - If category is given (and not "random"), pick from that category.
        - Otherwise pick from all categories, avoiding recently played sounds.
        """
        if specific_file:
            for cat_files in self.sounds.values():
                for f in cat_files:
                    if os.path.basename(f) == specific_file:
                        return f
            return None

        if category and category != "random" and category in self.sounds:
            candidates = self.sounds[category]
        else:
            candidates = self.get_all_files()

        if not candidates:
            return None

        # Filter out recently played sounds
        available = [f for f in candidates if f not in self.recently_played]

        # If all have been played recently, pick the least recent
        if not available:
            available = candidates

        return random.choice(available)

    def _pick_sound_weighted(self, category_weights=None):
        """
        Pick a sound using weighted category selection.
        category_weights: dict like {"predator": 3, "distress": 4, "startle": 1, "custom": 2}
        """
        if not category_weights:
            return self._pick_sound()

        # Build weighted category list from available categories
        weighted = []
        for cat, weight in category_weights.items():
            if cat in self.sounds and self.sounds[cat]:
                weighted.extend([cat] * weight)

        if not weighted:
            return self._pick_sound()

        chosen_category = random.choice(weighted)
        return self._pick_sound(category=chosen_category)

    def play(self, category=None, specific_file=None, category_weights=None):
        """
        Play a sound. Returns the filename played, or None if nothing to play.
        """
        with self._lock:
            if specific_file:
                sound_file = self._pick_sound(specific_file=specific_file)
            elif category_weights and not category:
                sound_file = self._pick_sound_weighted(category_weights)
            else:
                sound_file = self._pick_sound(category=category)

            if not sound_file:
                return None

            # Apply volume with slight jitter for anti-habituation
            jitter = random.randint(-5, 5)
            effective_volume = max(0, min(100, self.volume + jitter))

            try:
                pygame.mixer.music.load(sound_file)
                pygame.mixer.music.set_volume(effective_volume / 100.0)
                pygame.mixer.music.play()
                self.playing = True
                self.current_sound = os.path.basename(sound_file)
                self.recently_played.append(sound_file)
            except Exception as e:
                print(f"Error playing {sound_file}: {e}")
                return None

            return self.current_sound

    def stop(self):
        """Stop current playback."""
        with self._lock:
            pygame.mixer.music.stop()
            self.playing = False
            self.current_sound = None

    def set_volume(self, level):
        """Set volume (0-100)."""
        self.volume = max(0, min(100, level))
        if self.playing:
            pygame.mixer.music.set_volume(self.volume / 100.0)

    def is_playing(self):
        """Check if audio is currently playing."""
        if self.playing and not pygame.mixer.music.get_busy():
            self.playing = False
            self.current_sound = None
        return self.playing

    def get_current(self):
        """Return the currently playing sound filename, or None."""
        self.is_playing()  # refresh state
        return self.current_sound
