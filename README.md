# MiniMax Bot (Paper→Live)

## Dev (Codex/Codespaces)
1. Paste repo files.
2. `pip install -r requirements.txt`
3. Copy `.env.example` → `.env` (leave `PAPER_MODE=true`)
4. Run: `make dev`

## Prod (Oracle VPS)
1. `sudo apt update && sudo apt install -y docker.io docker-compose-plugin git`
2. `git clone <YOUR_REPO> && cd <repo>`
3. `cp .env.example .env` → fill keys, set `PAPER_MODE=false` when ready
4. `make update`  (builds & runs)
5. Logs: `make logs`
6. Health: `curl http://localhost:8080/health`

## Safety
- Session drawdown guard (`SESSION_MAX_DRAWDOWN_USD`) pauses trading for the day.
- Loss-streak pause & cooldown reduce churn.
- Live mode refuses to start if keys missing.
