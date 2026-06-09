"""
Timezone utilities for unified time handling across the application.

Supports configuration via:
1. Environment variable: TIMEZONE (highest priority)
2. config/server.json: timezone.default
3. Default: UTC
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


# Cache for loaded config
_config_cache: Optional[dict] = None
_timezone_cache: Optional[ZoneInfo] = None


def _load_server_config() -> dict:
    """Load server.json configuration."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_path = Path(__file__).parent.parent.parent / "config" / "server.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            _config_cache = json.load(f)
    else:
        _config_cache = {}

    return _config_cache


def get_timezone() -> ZoneInfo:
    """
    Get the configured timezone.

    Priority:
    1. TIMEZONE environment variable
    2. config/server.json timezone.default
    3. Default: UTC
    """
    global _timezone_cache
    if _timezone_cache is not None:
        return _timezone_cache

    # Check environment variable first
    tz_name = os.environ.get("TIMEZONE")

    # Fall back to config file
    if not tz_name:
        config = _load_server_config()
        tz_name = config.get("timezone", {}).get("default", "UTC")

    try:
        _timezone_cache = ZoneInfo(tz_name)
    except Exception:
        # Fallback to UTC if invalid timezone
        _timezone_cache = ZoneInfo("UTC")

    return _timezone_cache


def get_timezone_name() -> str:
    """Get the timezone name string."""
    tz_name = os.environ.get("TIMEZONE")
    if not tz_name:
        config = _load_server_config()
        tz_name = config.get("timezone", {}).get("default", "UTC")
    return tz_name


def now() -> datetime:
    """Get current datetime in configured timezone."""
    return datetime.now(get_timezone())


def now_iso() -> str:
    """Get current datetime as ISO format string with timezone info."""
    return now().isoformat()


def format_datetime(dt: Optional[datetime] = None, fmt: Optional[str] = None) -> str:
    """
    Format datetime according to configured format.

    Args:
        dt: Datetime to format (defaults to now)
        fmt: Format string (defaults to config datetime format)

    Returns:
        Formatted datetime string
    """
    if dt is None:
        dt = now()
    elif dt.tzinfo is None:
        # If naive datetime, assume it's in the configured timezone
        dt = dt.replace(tzinfo=get_timezone())

    if fmt is None:
        config = _load_server_config()
        fmt = config.get("timezone", {}).get("format", {}).get("datetime", "%Y-%m-%d %H:%M:%S")

    return dt.strftime(fmt)


def format_time(dt: Optional[datetime] = None) -> str:
    """Format time only (HH:MM:SS)."""
    if dt is None:
        dt = now()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_timezone())

    config = _load_server_config()
    fmt = config.get("timezone", {}).get("format", {}).get("time_only", "%H:%M:%S")
    return dt.strftime(fmt)


def parse_iso(iso_string: str) -> datetime:
    """Parse ISO format string to timezone-aware datetime."""
    dt = datetime.fromisoformat(iso_string)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_timezone())
    return dt


def to_local(dt: datetime) -> datetime:
    """Convert datetime to configured timezone."""
    if dt.tzinfo is None:
        # Assume UTC if naive
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(get_timezone())


def clear_cache():
    """Clear timezone cache (useful for testing or config reload)."""
    global _config_cache, _timezone_cache
    _config_cache = None
    _timezone_cache = None
