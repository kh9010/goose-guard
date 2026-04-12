"""
GPIO motion sensor monitor for Goose Guard.
Listens for PIR sensor triggers and plays deterrent sounds.
Optional component -- only runs if motion detection is enabled in config.
"""

import random
import threading
import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False


DEFAULT_PIN = 17
DEFAULT_COOLDOWN = 300  # seconds


class MotionMonitor:
    def __init__(self, sound_engine, config, log_callback=None):
        self.sound_engine = sound_engine
        self.config = config
        self.log_callback = log_callback or (lambda msg, src: None)
        self.pin = config.get("motion", {}).get("pin", DEFAULT_PIN)
        self.last_trigger = 0
        self._running = False
        self._thread = None

    def start(self):
        """Start monitoring the PIR sensor."""
        if not GPIO_AVAILABLE:
            print("GPIO not available -- motion detection disabled")
            return False

        motion_cfg = self.config.get("motion", {})
        if not motion_cfg.get("enabled", False):
            return False

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Stop monitoring."""
        self._running = False
        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup(self.pin)
            except Exception:
                pass

    def _monitor_loop(self):
        """Poll the PIR sensor and trigger sounds when motion detected."""
        while self._running:
            try:
                if GPIO.input(self.pin):
                    self._on_motion()
                time.sleep(0.5)
            except Exception as e:
                print(f"Motion monitor error: {e}")
                time.sleep(1)

    def _on_motion(self):
        """Handle a motion detection event."""
        mode = self.config.get("mode", "manual")
        if mode not in ("motion", "motion+auto"):
            return

        cooldown = self.config.get("motion", {}).get(
            "cooldown_seconds", DEFAULT_COOLDOWN
        )
        now = time.time()
        if now - self.last_trigger < cooldown:
            return

        self.last_trigger = now
        category_weights = self.config.get("category_weights")

        # Play a burst of 2-3 sounds in quick succession
        burst_count = random.randint(2, 3)
        for i in range(burst_count):
            played = self.sound_engine.play(category_weights=category_weights)
            if played:
                self.log_callback(played, "motion")
            if i < burst_count - 1:
                time.sleep(random.randint(3, 8))
