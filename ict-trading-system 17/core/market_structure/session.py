"""Session Detection — identifies which trading session is active.

Replaces the hardcoded session_active=True in the pipeline.
Uses UTC times from config/structure.yaml.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Optional

import structlog
import yaml

from core.models import SessionName

logger = structlog.get_logger(__name__)


class SessionDetector:
    """Determines the active trading session from UTC time."""

    def __init__(self, config_path: str = "config/structure.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.sessions_cfg = cfg["sessions"]

        # Parse session windows into time objects
        self.windows: dict[SessionName, tuple[time, time]] = {}
        for name, window in self.sessions_cfg.items():
            start = time.fromisoformat(window["start_utc"])
            end = time.fromisoformat(window["end_utc"])
            session_enum = SessionName(name)
            self.windows[session_enum] = (start, end)

    def get_active_session(self, utc_now: Optional[datetime] = None) -> SessionName:
        """Return the most specific active session, or OFF_SESSION."""
        if utc_now is None:
            utc_now = datetime.now(timezone.utc)

        current_time = utc_now.time()

        # Check most specific first (ny_killzone is inside ny)
        if self._in_window(current_time, SessionName.NY_KILLZONE):
            return SessionName.NY_KILLZONE

        if self._in_window(current_time, SessionName.NY):
            return SessionName.NY

        if self._in_window(current_time, SessionName.LONDON):
            return SessionName.LONDON

        if self._in_window(current_time, SessionName.ASIA):
            return SessionName.ASIA

        return SessionName.OFF_SESSION

    def is_ny_active(self, utc_now: Optional[datetime] = None) -> bool:
        """Check if NY session (including killzone) is active."""
        session = self.get_active_session(utc_now)
        return session in (SessionName.NY, SessionName.NY_KILLZONE)

    def is_killzone_active(self, utc_now: Optional[datetime] = None) -> bool:
        """Check if the NY killzone window is active."""
        return self.get_active_session(utc_now) == SessionName.NY_KILLZONE

    def _in_window(self, current: time, session: SessionName) -> bool:
        """Check if current time falls within a session window."""
        if session not in self.windows:
            return False
        start, end = self.windows[session]
        if start <= end:
            return start <= current < end
        else:
            # Handles midnight crossing (e.g., 22:00 -> 06:00)
            return current >= start or current < end

    def get_session_range_times(
        self, session: SessionName, date: Optional[datetime] = None
    ) -> tuple[datetime, datetime]:
        """Get start/end datetime for a session on a given date."""
        if date is None:
            date = datetime.now(timezone.utc)

        if session not in self.windows:
            raise ValueError(f"Unknown session: {session}")

        start_time, end_time = self.windows[session]
        start_dt = datetime.combine(date.date(), start_time, tzinfo=timezone.utc)
        end_dt = datetime.combine(date.date(), end_time, tzinfo=timezone.utc)

        if end_dt <= start_dt:
            # Midnight crossing — end is next day
            from datetime import timedelta
            end_dt += timedelta(days=1)

        return start_dt, end_dt

    def is_weekend(self, utc_now: Optional[datetime] = None) -> bool:
        """Check if it's a weekend (no trading)."""
        if utc_now is None:
            utc_now = datetime.now(timezone.utc)
        # Markets closed from Friday ~22:00 UTC to Sunday ~22:00 UTC
        # Simplified: Saturday (5) and Sunday (6) are no-trade
        return utc_now.weekday() in (5, 6)
