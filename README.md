# renfield-mcp-calendar

Unified MCP server for calendar access — connect **Exchange (EWS)**, **Google Calendar**, and **CalDAV** (Nextcloud, ownCloud, Radicale) through a single [Model Context Protocol](https://modelcontextprotocol.io/) interface.

## Features

- **Multi-calendar** — Configure multiple calendar accounts via YAML, query them individually or all at once
- **Cross-calendar merge** — `list_events` without a calendar parameter returns events from ALL calendars sorted chronologically
- **Three backends** — Exchange Web Services (EWS), Google Calendar API, CalDAV
- **No passwords in config** — Credentials referenced via environment variable names
- **Lazy connections** — Backend clients are initialized on first use, not at startup
- **Async-ready** — All blocking I/O wrapped with `asyncio.run_in_executor`
- **Google OAuth2 helper** — Built-in `--auth google` CLI for initial token setup

## Installation

```bash
pip install renfield-mcp-calendar
```

Or directly from GitHub:

```bash
pip install "renfield-mcp-calendar @ https://github.com/ebongard/renfield-mcp-calendar/archive/refs/heads/main.tar.gz"
```

## Configuration

Set `CALENDAR_CONFIG` to point to your YAML config file (default: `/config/calendar_accounts.yaml`).

### Example `calendar_accounts.yaml`

```yaml
calendars:
  # Exchange 2019 (on-premise, direct EWS endpoint)
  - name: work
    label: "Work Calendar"
    type: ews
    ews_url: "https://exchange.example.com/EWS/Exchange.asmx"
    username_env: CALENDAR_WORK_USERNAME
    password_env: CALENDAR_WORK_PASSWORD

  # Google Calendar (OAuth2 Desktop Flow)
  - name: family
    label: "Family Calendar"
    type: google
    calendar_id: "primary"
    credentials_file: "/config/google_calendar_credentials.json"
    token_file: "/data/google_calendar_token.json"

  # Nextcloud / CalDAV
  - name: club
    label: "Club Calendar"
    type: caldav
    url: "https://nextcloud.example.com/remote.php/dav/calendars/user/club/"
    username_env: CALENDAR_CLUB_USERNAME
    password_env: CALENDAR_CLUB_PASSWORD
```

**Security:** Passwords and tokens are **never** stored in the YAML file — use `*_env` fields to reference environment variable names.

### Backend-specific notes

| Backend | Library | Auth | Notes |
|---------|---------|------|-------|
| **EWS** | [exchangelib](https://github.com/ecederstrand/exchangelib) | NTLM/Basic | Direct EWS URL, no Autodiscover needed |
| **Google** | [google-api-python-client](https://github.com/googleapis/google-api-python-client) | OAuth2 Desktop Flow | Token auto-refresh, one-time browser auth |
| **CalDAV** | [caldav](https://github.com/python-caldav/caldav) | Basic Auth | Works with Nextcloud, ownCloud, Radicale, etc. |

### Google Calendar setup (one-time)

1. [Google Cloud Console](https://console.cloud.google.com/) → Create project → Enable **Google Calendar API**
2. Create **OAuth2 credentials** (Desktop App) → Download `credentials.json`
3. Place as `google_calendar_credentials.json` in your config directory
4. Run the auth flow:
   ```bash
   python -m renfield_mcp_calendar --auth google --calendar family
   ```
5. Complete the browser-based authorization — token is saved automatically

## MCP Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `list_calendars` | — | List all configured calendar accounts |
| `list_events` | `calendar?`, `start`, `end` | Events from one or all calendars. Empty `calendar` = merged from all. |
| `create_event` | `calendar`, `title`, `start`, `end`, `description?`, `location?` | Create a new event |
| `update_event` | `calendar`, `event_id`, `title?`, `start?`, `end?`, ... | Update specific fields of an event |
| `delete_event` | `calendar`, `event_id` | Delete an event |
| `get_event` | `calendar`, `event_id` | Get a single event with full details |

### Example queries (via LLM)

- *"Was steht heute an?"* → `list_events()` (all calendars, today)
- *"Was steht im Firmenkalender diese Woche?"* → `list_events(calendar="work", start="...", end="...")`
- *"Erstelle einen Familientermin morgen um 14 Uhr: Zahnarzt"* → `create_event(calendar="family", ...)`
- *"Bin ich morgen Nachmittag frei?"* → `list_events(start="...", end="...")`

## Usage

```bash
# Run as MCP server (stdio transport)
python -m renfield_mcp_calendar

# Or via entry point
renfield-mcp-calendar

# Google OAuth2 setup (one-time)
python -m renfield_mcp_calendar --auth google --calendar family
```

### Claude Desktop / MCP client config

```json
{
  "mcpServers": {
    "calendar": {
      "command": "python",
      "args": ["-m", "renfield_mcp_calendar"],
      "env": {
        "CALENDAR_CONFIG": "/path/to/calendar_accounts.yaml",
        "CALENDAR_WORK_USERNAME": "user@example.com",
        "CALENDAR_WORK_PASSWORD": "secret"
      }
    }
  }
}
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (29 tests)
pytest tests/ -v
```

## License

MIT
