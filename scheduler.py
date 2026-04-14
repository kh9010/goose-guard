"""
Scheduler for Goose Guard.
Manages automated deterrent sessions at dawn, dusk, and midday.
Uses astral for sunrise/sunset calculation.
"""

import random
import threading
import time
from datetime import datetime, timedelta
from weakref import WeakSet

from apscheduler.schedulers.background import BackgroundScheduler
from astral import LocationInfo
from astral.sun import sun
from zoneinfo import ZoneInfo


# 9010 NE 41st St, Yarrow Point, WA 98004
DEFAULT_LAT = 47.6490
DEFAULT_LNG = -122.2100
DEFAULT_TIMEZONE = "America/Los_Angeles"


class DeterrentScheduler:
    def __init__(self, sound_engine, config, log_callback=None):
        self.sound_engine = sound_engine
        self.config = config
        self.log_callback = log_callback or (lambda msg, src: None)
        self.scheduler = BackgroundScheduler(timezone=DEFAULT_TIMEZONE)
        self._active_stop_events = WeakSet()
        self._sessions_lock = threading.Lock()
        self.location = LocationInfo(
            "Property", "WA", DEFAULT_TIMEZONE,
            DEFAULT_LAT, DEFAULT_LNG
        )

    def start(self):
        """Start the scheduler. Reschedules daily at midnight."""
        self.scheduler.add_job(
            self._schedule_today,
            "cron",
            hour=0, minute=5,
            id="daily_reschedule",
            replace_existing=True,
        )
        self._schedule_today()
        self.scheduler.start()

    def stop(self):
        """Shut down the scheduler."""
        self._stop_all_sessions()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _stop_all_sessions(self):
        """Signal all running deterrent sessions to stop."""
        with self._sessions_lock:
            for ev in self._active_stop_events:
                ev.set()

    def _get_sun_times(self):
        """Get today's sunrise and sunset times in the configured local timezone."""
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        s = sun(self.location.observer, date=datetime.now(tz).date(), tzinfo=tz)
        return s["sunrise"], s["sunset"]

    def _schedule_today(self):
        """Schedule today's deterrent sessions based on config."""
        schedule_config = self.config.get("schedule", {})
        mode = self.config.get("mode", "manual")

        if mode not in ("auto", "motion+auto"):
            return

        try:
            sunrise, sunset = self._get_sun_times()
        except Exception as e:
            print(f"Could not compute sun times: {e}. Skipping today's schedule.")
            return
        now = datetime.now(sunrise.tzinfo)

        # Remove old one-off jobs
        for job_id in ("dawn_session", "dusk_session", "midday_session"):
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass

        # Dawn session
        dawn_cfg = schedule_config.get("dawn", {})
        if dawn_cfg.get("enabled", True):
            offset = dawn_cfg.get("offset_minutes", -30)
            dawn_start = sunrise + timedelta(minutes=offset)
            if dawn_start > now:
                self.scheduler.add_job(
                    self._run_session,
                    "date",
                    run_date=dawn_start,
                    args=[dawn_cfg, "dawn"],
                    id="dawn_session",
                )

        # Dusk session
        dusk_cfg = schedule_config.get("dusk", {})
        if dusk_cfg.get("enabled", True):
            offset = dusk_cfg.get("offset_minutes", -30)
            dusk_start = sunset + timedelta(minutes=offset)
            if dusk_start > now:
                self.scheduler.add_job(
                    self._run_session,
                    "date",
                    run_date=dusk_start,
                    args=[dusk_cfg, "dusk"],
                    id="dusk_session",
                )

        # Midday patrol — pick a random hour in the remaining window
        midday_cfg = schedule_config.get("midday", {})
        if midday_cfg.get("enabled", True):
            earliest_hour = max(10, now.hour + 1)
            if earliest_hour <= 13:
                midday_hour = random.randint(earliest_hour, 13)
                midday_minute = random.randint(0, 59)
                midday_time = now.replace(
                    hour=midday_hour, minute=midday_minute, second=0, microsecond=0
                )
                if midday_time > now:
                    self.scheduler.add_job(
                        self._run_midday_burst,
                        "date",
                        run_date=midday_time,
                        args=[midday_cfg],
                        id="midday_session",
                    )

    def _is_quiet_hours(self):
        """Check if current time is within quiet hours."""
        quiet = self.config.get("schedule", {}).get("quiet_hours", {})
        if not quiet:
            return False

        now = datetime.now()
        try:
            start_h, start_m = map(int, quiet.get("start", "22:00").split(":"))
            end_h, end_m = map(int, quiet.get("end", "05:00").split(":"))
        except (ValueError, AttributeError):
            return False

        start = now.replace(hour=start_h, minute=start_m, second=0)
        end = now.replace(hour=end_h, minute=end_m, second=0)

        if start > end:
            # Quiet hours span midnight
            return now >= start or now <= end
        else:
            return start <= now <= end

    def _run_session(self, session_cfg, source_name):
        """Run a deterrent session (dawn or dusk)."""
        if self._is_quiet_hours():
            return

        duration = session_cfg.get("duration_minutes", 45)
        interval_min = max(1, int(session_cfg.get("interval_min", 120)))
        interval_max = max(interval_min, int(session_cfg.get("interval_max", 300)))
        category_weights = self.config.get("category_weights")

        stop_event = threading.Event()
        with self._sessions_lock:
            self._active_stop_events.add(stop_event)
        end_time = time.time() + (duration * 60)

        def session_loop():
            while not stop_event.is_set() and time.time() < end_time:
                if self._is_quiet_hours():
                    break
                if self.config.get("mode", "manual") not in ("auto", "motion+auto"):
                    break

                played = self.sound_engine.play(category_weights=category_weights)
                if played:
                    self.log_callback(played, source_name)

                delay = random.randint(interval_min, interval_max)
                # Sleep in small increments so we can stop quickly
                for _ in range(delay):
                    if stop_event.is_set():
                        return
                    time.sleep(1)

        t = threading.Thread(target=session_loop, daemon=True)
        t.start()

    def _run_midday_burst(self, midday_cfg):
        """Run a short midday burst of sounds."""
        if self._is_quiet_hours():
            return
        if self.config.get("mode", "manual") not in ("auto", "motion+auto"):
            return

        count = midday_cfg.get("count", 3)
        category_weights = self.config.get("category_weights")

        for i in range(count):
            played = self.sound_engine.play(category_weights=category_weights)
            if played:
                self.log_callback(played, "midday")
            if i < count - 1:
                time.sleep(random.randint(10, 30))

    def reschedule(self):
        """Call after config changes to re-plan today's sessions."""
        self._stop_all_sessions()
        self._schedule_today()

    def get_next_times(self):
        """Return upcoming sunrise/sunset for display."""
        try:
            sunrise, sunset = self._get_sun_times()
            return {
                "sunrise": sunrise.strftime("%I:%M %p"),
                "sunset": sunset.strftime("%I:%M %p"),
            }
        except Exception:
            return {"sunrise": "unknown", "sunset": "unknown"}
