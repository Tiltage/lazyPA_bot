# lazy_PAbot

A personal Telegram bot I built to serve as my day-to-day AI assistant. It connects to my Google account and lets me manage my calendar, tasks, and email entirely through chat — with two LLM backends I can swap between on the fly.

Vibecoded with Claude Code as my primary tool. It runs 24/7 on an Oracle Cloud free-tier VM and deploys automatically on every push via GitHub Actions.

---

## What it does

**Calendar**
- List upcoming events
- Create events — including all-day events, recurring events (RRULE), and events with locations (resolved to a precise address via Google Places API)
- Update or delete events, with recurring scope control (single occurrence vs. full series)
- Conflict detection before creating — queries only the target date window, not the full default range
- Month-view calendar rendered as an image (Pillow) with inline navigation

**Tasks**
- Create, view, update, and delete Google Tasks to-do items
- The agent knows to use tasks for timeless reminders and calendar events for time-blocked items

**Email**
- Summarise inbox, read full email bodies, and send/compose via Gmail
- Always fetches the full body before summarising — never works from snippet alone

**Conversation** (Future Implementation)
- Persistent per-session history with automatic summarisation when it gets long
- Switch LLM mid-session: `/claude` or `/gemini`
- `/clear` resets context and starts a fresh log file

---

## Architecture

```
Telegram ──► handlers.py ──► agent.py ──► tools/
                 │               │           ├── calendar.py  (Google Calendar + Places API)
                 │               │           ├── tasks.py     (Google Tasks)
                 │               │           └── gmail.py     (Gmail)
                 │               │
                 │           ClaudeAgent  (manual tool-use loop)
                 │           GeminiAgent  (automatic function calling)
                 │
                 └── ui.py / calendar_render.py  (Telegram HTML, Pillow images, inline keyboards)
```

- **Bot layer** (`bot.py`) — Telegram polling, command menu registration
- **Agent layer** (`agent.py`) — LLM orchestration for Claude and Gemini; tool dispatch; history compression
- **Interface layer** (`interface/`) — command routing, HTML sanitisation, Pillow calendar renderer, inline keyboard builders
- **Tools layer** (`tools/`) — Google API wrappers; `Tool` base class auto-generates both Anthropic and Gemini schemas from the same definition
- **Logging** (`conv_logger.py`) — one log file per conversation written to `logs/`, capturing all tool calls, LLM I/O, and errors

---

## Deployment

Push to `master` → GitHub Actions SSHs into an Oracle Cloud VM → pulls latest code → regenerates `.env` from repository secrets → restarts the systemd service (`lazypa`).

---

## Stack

| Layer | Technology |
|---|---|
| Bot framework | python-telegram-bot 21.6 |
| LLMs | Claude (Anthropic) · Gemini (Google) |
| Google APIs | Calendar · Gmail · Tasks · Places |
| Image rendering (Calendar) | Pillow |
| Auth | Google OAuth 2.0 |
| Config | python-dotenv + INI (.config) |
| CI/CD | GitHub Actions → Oracle Cloud VM (systemd) |

---

## What I applied building this

For anyone skimming from a technical angle — this project touches:

- **API integration**: Google OAuth 2.0 flow, multi-scope token management (Calendar, Gmail, Tasks), Google Places API
- **LLM tool use**: Anthropic tool-use loop (manual), Gemini automatic function calling — same tool registry drives both
- **Software design**: Abstract base class for tools that auto-generates provider-specific schemas; registry pattern; layered architecture with clear separation of concerns
- **Prompt engineering**: Structured system prompt rules, targeted context retrieval, disambiguation logic, conflict detection strategy
- **CI/CD**: GitHub Actions workflow with SSH deployment, secret injection, conditional dependency installs, systemd service management
- **Cloud infrastructure**: Oracle Cloud Always Free VM, SSH key auth, systemd service
- **Security**: Chat ID allowlist guard on every handler; all secrets in `.env` and GitHub secrets, never in source

---

## Setup (self-hosting)

1. Clone and create a virtualenv
2. Register a Telegram bot via BotFather and get the token
3. Create a Google Cloud project, enable Calendar/Gmail/Tasks/Places APIs, download `credentials.json`, run `python auth.py` for the initial OAuth flow
4. Copy `.env.example` → `.env` and fill in your keys
5. `pip install -r requirements.txt && python bot.py`

For automated deployment, set the following GitHub secrets: `ORACLE_HOST`, `ORACLE_SSH_KEY`, `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_CHAT_ID`.
