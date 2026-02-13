"""YAML configuration loading for calendar accounts."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger("renfield-mcp-calendar")

CONFIG_PATH = os.environ.get("CALENDAR_CONFIG", "/config/calendar_accounts.yaml")

VALID_TYPES = {"ews", "google", "caldav"}


@dataclass
class CalendarAccount:
    """A single calendar account configuration."""

    name: str
    label: str
    type: str  # ews, google, caldav
    config: dict[str, Any] = field(default_factory=dict)


def load_config() -> dict[str, CalendarAccount]:
    """Load and validate calendar_accounts.yaml.

    Returns dict of name -> CalendarAccount.
    """
    path = CONFIG_PATH
    if not os.path.isfile(path):
        logger.warning("Config file not found: %s", path)
        return {}

    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    if not raw or "calendars" not in raw:
        logger.warning("No 'calendars' key in config file")
        return {}

    accounts: dict[str, CalendarAccount] = {}
    seen_names: set[str] = set()

    for entry in raw["calendars"]:
        name = entry.get("name", "").strip()
        if not name:
            raise ValueError("Calendar missing 'name' field")
        if name in seen_names:
            raise ValueError(f"Duplicate calendar name: '{name}'")
        seen_names.add(name)

        cal_type = entry.get("type", "").strip().lower()
        if cal_type not in VALID_TYPES:
            raise ValueError(f"Calendar '{name}': unknown type '{cal_type}'. Must be one of: {VALID_TYPES}")

        label = entry.get("label", name)

        # Collect type-specific config (everything except name/label/type)
        config = {k: v for k, v in entry.items() if k not in ("name", "label", "type")}

        # Validate required fields per type
        if cal_type == "ews":
            if "ews_url" not in config:
                raise ValueError(f"Calendar '{name}' (ews): 'ews_url' is required")
            if "username_env" not in config or "password_env" not in config:
                raise ValueError(f"Calendar '{name}' (ews): 'username_env' and 'password_env' are required")
            # Warn if env vars not set
            for env_key in ("username_env", "password_env"):
                env_var = config[env_key]
                if not os.environ.get(env_var):
                    logger.warning("Calendar '%s': env var '%s' not set", name, env_var)

        elif cal_type == "google":
            if "credentials_file" not in config:
                raise ValueError(f"Calendar '{name}' (google): 'credentials_file' is required")

        elif cal_type == "caldav":
            if "url" not in config:
                raise ValueError(f"Calendar '{name}' (caldav): 'url' is required")
            if "username_env" not in config or "password_env" not in config:
                raise ValueError(f"Calendar '{name}' (caldav): 'username_env' and 'password_env' are required")
            for env_key in ("username_env", "password_env"):
                env_var = config[env_key]
                if not os.environ.get(env_var):
                    logger.warning("Calendar '%s': env var '%s' not set", name, env_var)

        accounts[name] = CalendarAccount(name=name, label=label, type=cal_type, config=config)

    return accounts
