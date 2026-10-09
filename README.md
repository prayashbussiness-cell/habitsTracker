# Start Your Day: FastAPI + Supabase

```
Browser (static/index.html)  ->  FastAPI (main.py)  ->  Supabase (Postgres)
```
The browser never sees your Supabase key. Same layout as the Student Register project.

## Setup
1. **Supabase**: create a project, open *SQL Editor*, paste and run `schema.sql`.
2. **Keys**: copy `.env.example` to `.env` and fill it in.
   - `SUPABASE_URL`: Project Settings > API > Project URL
   - `SUPABASE_KEY`: the **secret** key `sb_secret_...` (Settings > API Keys; server only, NOT the publishable key)
   - `APP_SECRET`: optional. Long random string that signs login tokens (derived from the key if omitted)
3. **Run**
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```
Open http://127.0.0.1:8000, choose **Sign up** (name + 10-digit phone), then use the app. API docs: /docs

## How it works
- **Add Card** is a one-time setup. Every habit card appears on Dashboard and Daily Tasks each day.
- **Skip today** leaves that habit out of that day's efficiency and habit counts.
- Efficiency = average of task completion and mean habit progress (progress capped at 100%).
- Stats are recalculated and stored in `daily_statistics` after every change.
- A habit card only counts from the day it was created, so old days are not penalised.

## API (all except auth need `Authorization: Bearer <token>`)
| Route | Purpose |
|---|---|
| POST /api/auth/signup, /api/auth/login | name + phone, returns token |
| GET /api/me | current user |
| GET /api/day?date= | tasks, habit progress, day note |
| GET /api/history?days= | per-day stats (weekly chart, history list, streak dots) |
| POST/PATCH/DELETE /api/tasks | add, tick, delete tasks |
| GET/POST/PUT/DELETE /api/cards | habit cards |
| PUT /api/progress | actual value, note, skipped (per card per date) |
| PUT /api/notes | day note |
| GET/POST/PUT/DELETE /api/goals | goals |
| GET /api/summary | monthly, yearly, streaks, category performance |

## Notes
- Login is name + phone with no OTP or password, as requested. Anyone who knows both can log in. Add Supabase Auth or SMS OTP before real use.
- Tokens do not expire yet.
- Do not commit `.env` (already in `.gitignore`).
