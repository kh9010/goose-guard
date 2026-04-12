"""
Goose Guard — Remote sound deterrent system for scaring geese.
Flask web server serving the control interface and REST API.
"""

import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request, send_from_directory

from gpio_monitor import MotionMonitor
from scheduler import DeterrentScheduler
from sound_agent import SoundAgent
from sound_engine import SoundEngine
from system_info import collect as collect_system_info

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
HARDWARE_PATH = BASE_DIR / "hardware.json"
LOG_FILE = BASE_DIR / "activity.jsonl"
SOUNDS_DIR = BASE_DIR / "sounds"
STATIC_DIR = BASE_DIR / "static"

MAX_LOG_ENTRIES = 50
LOG_FILE_ROTATE_AT = 1000  # truncate to last MAX_LOG_ENTRIES when file exceeds this

app = Flask(__name__, static_folder=str(STATIC_DIR))

# Global state
activity_log = deque(maxlen=MAX_LOG_ENTRIES)
log_lock = threading.Lock()
PROCESS_START = time.time()


def load_config():
    """Load configuration from disk."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "mode": "auto",
            "volume": 85,
            "location": {
                "name": "Property",
                "region": "",
                "timezone": "America/Los_Angeles",
                "latitude": 47.6456,
                "longitude": -122.2187,
            },
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
                                 "startle": 1, "custom": 2,
                                 "generated": 3},
            "motion": {"enabled": False, "pin": 17, "cooldown_seconds": 300},
        }


def save_config(config):
    """Persist configuration to disk."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def _load_activity_log():
    """Rehydrate the in-memory activity log from disk on startup."""
    if not LOG_FILE.exists():
        return
    try:
        with open(LOG_FILE) as f:
            lines = f.readlines()
    except OSError:
        return

    # Rotate the file if it has grown unreasonably long.
    if len(lines) > LOG_FILE_ROTATE_AT:
        lines = lines[-MAX_LOG_ENTRIES:]
        try:
            with open(LOG_FILE, "w") as f:
                f.writelines(lines)
        except OSError:
            pass

    with log_lock:
        for line in lines[-MAX_LOG_ENTRIES:]:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Oldest first in file, newest at left of the deque.
            activity_log.appendleft(entry)


def _persist_event(entry):
    """Append a single event to the on-disk activity log."""
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def log_event(sound_name, source):
    """Log a sound event with timestamp."""
    now = datetime.now()
    entry = {
        "time": now.strftime("%H:%M"),
        "timestamp": now.isoformat(timespec="seconds"),
        "sound": sound_name,
        "source": source,
    }
    with log_lock:
        activity_log.appendleft(entry)
    _persist_event(entry)


def _load_hardware():
    """Load hardware shopping list from disk."""
    try:
        with open(HARDWARE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"items": []}


# Initialize components
config = load_config()
engine = SoundEngine(sounds_dir=str(SOUNDS_DIR))
engine.set_volume(config.get("volume", 85))
scheduler = DeterrentScheduler(engine, config, log_callback=log_event)
motion = MotionMonitor(engine, config, log_callback=log_event)
agent = SoundAgent(SOUNDS_DIR, engine, log_callback=log_event)

# Weekly background agent that generates fresh deterrent sounds so geese
# don't habituate. Runs early Monday morning. Separate scheduler instance
# so it doesn't tangle with the deterrent session scheduler.
agent_scheduler = BackgroundScheduler()
agent_scheduler.add_job(
    agent.run,
    "cron",
    day_of_week="mon",
    hour=3,
    minute=0,
    id="weekly_sound_agent",
    replace_existing=True,
)

# Rehydrate activity log from disk
_load_activity_log()


# --- Static files ---

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/status")
def status_page():
    return send_from_directory(str(STATIC_DIR), "status.html")


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


# --- Status page endpoints ---

@app.route("/api/system")
def api_system():
    """System vitals for the status page."""
    info = collect_system_info()
    info["process_uptime_seconds"] = int(time.time() - PROCESS_START)
    info["mode"] = config.get("mode", "manual")
    info["playing"] = engine.is_playing()
    info["current_sound"] = engine.get_current()
    info["volume"] = engine.volume
    info["sun"] = scheduler.get_next_times()
    info["location"] = config.get("location", {})
    info["sound_counts"] = {k: len(v) for k, v in engine.get_sounds().items()}
    return jsonify(info)


@app.route("/api/hardware")
def api_hardware():
    return jsonify(_load_hardware())


@app.route("/api/location", methods=["GET"])
def api_location_get():
    return jsonify(config.get("location", {}))


@app.route("/api/sounds/delete", methods=["POST"])
def api_sounds_delete():
    """Remove a sound file from disk."""
    data = request.get_json(silent=True) or {}
    sound = data.get("sound")
    category = data.get("category")
    if not sound or not category:
        return jsonify({
            "status": "error",
            "message": "sound and category required",
        }), 400

    # Defend against path traversal
    for piece in (sound, category):
        if not isinstance(piece, str) or "/" in piece or "\\" in piece or piece.startswith("."):
            return jsonify({"status": "error", "message": "invalid name"}), 400

    sounds_root = SOUNDS_DIR.resolve()
    target = (SOUNDS_DIR / category / sound).resolve()
    try:
        target.relative_to(sounds_root)
    except ValueError:
        return jsonify({"status": "error", "message": "path outside sounds dir"}), 400

    if not target.exists() or not target.is_file():
        return jsonify({"status": "error", "message": "not found"}), 404

    try:
        target.unlink()
    except OSError as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    engine._scan_sounds()
    log_event(sound, "removed")
    return jsonify({"status": "ok", "removed": sound})


@app.route("/api/agent/run", methods=["POST"])
def api_agent_run():
    """Run the sound agent immediately (handy for testing and first-run)."""
    threading.Thread(target=agent.run, daemon=True).start()
    return jsonify({"status": "ok", "message": "Sound agent started"})


@app.route("/api/agent/status")
def api_agent_status():
    """Return info about the sound agent and its next scheduled run."""
    info = agent.status()
    next_run = None
    try:
        job = agent_scheduler.get_job("weekly_sound_agent")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    except Exception:
        pass
    info["next_run"] = next_run
    return jsonify(info)


@app.route("/api/location", methods=["POST"])
def api_location_set():
    data = request.get_json(silent=True) or {}
    location = dict(config.get("location") or {})

    try:
        if "latitude" in data:
            lat = float(data["latitude"])
            if not -90 <= lat <= 90:
                raise ValueError("latitude must be between -90 and 90")
            location["latitude"] = lat
        if "longitude" in data:
            lng = float(data["longitude"])
            if not -180 <= lng <= 180:
                raise ValueError("longitude must be between -180 and 180")
            location["longitude"] = lng
    except (TypeError, ValueError) as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    for key in ("name", "region", "timezone"):
        if key in data and isinstance(data[key], str):
            location[key] = data[key].strip()

    config["location"] = location
    save_config(config)
    scheduler.reschedule()
    return jsonify({
        "status": "ok",
        "location": location,
        "note": "Timezone changes take effect after a service restart.",
    })


# --- Main ---

if __name__ == "__main__":
    # Start scheduled deterrent sessions
    scheduler.start()

    # Start motion detection if enabled
    motion.start()

    # Start the weekly sound-generation agent
    agent_scheduler.start()

    # If this is the first boot and no agent sounds exist yet, seed one
    # so the "generated" category isn't empty out of the box.
    if not agent.has_generated_sounds():
        threading.Thread(target=agent.run, daemon=True).start()

    print("=" * 50)
    print("  Goose Guard is running")
    print("  Control panel: http://gooseguard.local:5000")
    print("  Status page:   http://gooseguard.local:5000/status")
    print("=" * 50)

    app.run(host="0.0.0.0", port=5000, debug=False)
