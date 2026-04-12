"""
Goose Guard — Remote sound deterrent system for scaring geese.
Flask web server serving the control interface and REST API.
"""

import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from gpio_monitor import MotionMonitor
from scheduler import DeterrentScheduler
from sound_engine import SoundEngine

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
SOUNDS_DIR = BASE_DIR / "sounds"
STATIC_DIR = BASE_DIR / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR))

# Global state
activity_log = deque(maxlen=50)
log_lock = threading.Lock()


def load_config():
    """Load configuration from disk."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "mode": "auto",
            "volume": 85,
            "schedule": {
                "dawn": {"enabled": True, "offset_minutes": -30,
                         "duration_minutes": 45, "interval_min": 120,
                         "interval_max": 300},
                "dusk": {"enabled": True, "offset_minutes": -30,
                         "duration_minutes": 45, "interval_min": 120,
                         "interval_max": 300},
                "midday": {"enabled": True, "count": 3},
                "quiet_hours": {"start": "22:00", "end": "05:00"},
            },
            "category_weights": {"predator": 3, "distress": 4,
                                 "startle": 1, "custom": 2},
            "motion": {"enabled": False, "pin": 17, "cooldown_seconds": 300},
        }


def save_config(config):
    """Persist configuration to disk."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def log_event(sound_name, source):
    """Log a sound event with timestamp."""
    with log_lock:
        activity_log.appendleft({
            "time": datetime.now().strftime("%H:%M"),
            "sound": sound_name,
            "source": source,
        })


# Initialize components
config = load_config()
engine = SoundEngine(sounds_dir=str(SOUNDS_DIR))
engine.set_volume(config.get("volume", 85))
scheduler = DeterrentScheduler(engine, config, log_callback=log_event)
motion = MotionMonitor(engine, config, log_callback=log_event)


# --- Static files ---

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(str(STATIC_DIR), filename)


# --- API endpoints ---

@app.route("/api/status")
def api_status():
    sun_times = scheduler.get_next_times()
    return jsonify({
        "playing": engine.is_playing(),
        "current_sound": engine.get_current(),
        "volume": engine.volume,
        "mode": config.get("mode", "manual"),
        "sunrise": sun_times.get("sunrise"),
        "sunset": sun_times.get("sunset"),
    })


@app.route("/api/play", methods=["POST"])
def api_play():
    data = request.get_json(silent=True) or {}
    category = data.get("category")
    sound = data.get("sound")
    category_weights = config.get("category_weights")

    played = engine.play(
        category=category,
        specific_file=sound,
        category_weights=category_weights if not category and not sound else None,
    )

    if played:
        log_event(played, "manual")
        return jsonify({"status": "playing", "sound": played})
    else:
        return jsonify({"status": "error", "message": "No sounds available"}), 404


@app.route("/api/stop", methods=["POST"])
def api_stop():
    engine.stop()
    return jsonify({"status": "stopped"})


@app.route("/api/volume", methods=["POST"])
def api_volume():
    data = request.get_json(silent=True) or {}
    level = data.get("level", 85)
    level = max(0, min(100, int(level)))
    engine.set_volume(level)
    config["volume"] = level
    save_config(config)
    return jsonify({"status": "ok", "volume": level})


@app.route("/api/sounds")
def api_sounds():
    return jsonify(engine.get_sounds())


@app.route("/api/schedule")
def api_schedule():
    sun_times = scheduler.get_next_times()
    return jsonify({
        "schedule": config.get("schedule", {}),
        "sunrise": sun_times.get("sunrise"),
        "sunset": sun_times.get("sunset"),
    })


@app.route("/api/schedule", methods=["POST"])
def api_schedule_update():
    data = request.get_json(silent=True) or {}
    config["schedule"] = data.get("schedule", config.get("schedule", {}))
    save_config(config)
    scheduler.reschedule()
    return jsonify({"status": "ok", "schedule": config["schedule"]})


@app.route("/api/mode", methods=["POST"])
def api_mode():
    data = request.get_json(silent=True) or {}
    new_mode = data.get("mode", "manual")
    if new_mode not in ("manual", "auto", "motion", "motion+auto"):
        return jsonify({"status": "error", "message": "Invalid mode"}), 400
    config["mode"] = new_mode
    save_config(config)
    scheduler.reschedule()
    return jsonify({"status": "ok", "mode": new_mode})


@app.route("/api/log")
def api_log():
    with log_lock:
        return jsonify(list(activity_log))


# --- Main ---

if __name__ == "__main__":
    # Start scheduled deterrent sessions
    scheduler.start()

    # Start motion detection if enabled
    motion.start()

    print("=" * 50)
    print("  Goose Guard is running")
    print("  Open http://gooseguard.local:5000 on your phone")
    print("=" * 50)

    app.run(host="0.0.0.0", port=5000, debug=False)
