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
| GET/POST/PUT/DELETE /api/ideas, PATCH /api/ideas/{id}/skip | Ideas page (name, details, time required, advantage, skip) |
| GET/PUT /api/condition | Body condition: mood index and body strength, 0-10 per day |

## Notes
- Login is name + phone with no OTP or password, as requested. Anyone who knows both can log in. Add Supabase Auth or SMS OTP before real use.
- Tokens do not expire yet.
- Do not commit `.env` (already in `.gitignore`).

## Stay logged in / reliability (v2)
- The login token is kept in the browser until you press **Log out**. Refreshing the page, a slow server, a database error or a lost connection never logs you out; only a genuinely invalid token (HTTP 401) does.
- Every refresh (and returning to the tab) reloads the latest tasks, habits and stats from Supabase.
- Backend uses one Supabase client per thread and retries failed calls on a fresh client (fixes `[Errno 11] Resource temporarily unavailable`).
- Statistics recalculation is best-effort, so a saved task is never reported as failed because of it.
- Set `APP_SECRET` (or keep `SUPABASE_KEY` unchanged) on Render so existing login tokens stay valid between deploys.

## Ideas page + Body condition (v3)
- **Ideas** (sidebar, below Add Card): save anything on your mind with name, details, time required and advantage. Edit, delete or **Skip** (dimmed and moved to the bottom; Undo skip brings it back).
- **Body condition** (Dashboard, beside Daily efficiency): pick Mood index 0-10 and Body strength 0-10 for the selected day. Saved instantly; a 7-day trend shows below.
- **Existing database:** run `migration_ideas_and_condition.sql` once in Supabase > SQL Editor (new installs get it from `schema.sql`). Until then the rest of the app keeps working and a notice appears.

## v4: hours, mood per habit, M counter, priority order
- **Task hours**: every task has an hour counter (0 to 99, steps of 0.25). Saved instantly.
- **Mood index per habit**: each habit card has a 0-10 mood field for how you felt doing it that day.
- **Daily efficiency card** now shows Tasks % and Habits % as separate bars, the overall % in the ring, and *Task hours done* / *Habit hours done* (habits counted when their unit is hour or min).
- **M counter** (Body condition card): tap + / - to count per day. Shown as just "M".
- **Current streak card removed** from the Dashboard.
- **Tasks are always sorted** high, then med, then low (Dashboard and Daily Tasks).
- **Existing database:** run `migration_v4_hours_mood_m.sql` once in Supabase > SQL Editor *before* using this version (new installs get it from `schema.sql`).
- If `migration_v4_hours_mood_m.sql` has not been run yet, the app still loads; saving hours, a habit mood or the M counter shows "Database needs one update: run migration_v4_hours_mood_m.sql".

## v5: day story, God counter, Monthly Target
- **Overall story of the day**: dropdown under "START YOUR DAY" on the Dashboard (Fight All Day, I messed up today, I won today, Took a Leave today, I am frustrated today). Saved per day. Change the labels in the `STORY` constant at the top of the script in `static/index.html`.
- **God counter**: sits beside the **M** counter in the Body condition card, counted per day.
- **Monthly Target** (new sidebar page): cards for August, September and October. Open a month to see its target rows (tick, hours, category, priority, delete, same look as Daily Tasks). The top card shows the **total hours spent that month**, hours on completed targets and how many are done. Change the months in `TMON` in `static/index.html`.
- New API: `GET/POST /api/targets`, `PATCH/DELETE /api/targets/{id}`; `/api/condition` also accepts `story` and `god_count`.
- **Existing database:** run `migration_v5_story_god_targets.sql` once in Supabase > SQL Editor (new installs get it from `schema.sql`). Until then the app still loads and shows a notice.

## v6: Ego page
- **Ego** (sidebar, below Monthly Target): ranked cards with the same fields as Daily Tasks: name, hours, category and priority, plus tick and delete.
- **Rank**: type a number in the box on the left (1 = top) and the card jumps to that place. You can also set the rank when adding or editing a card.
- **Drag and drop**: hold the dotted handle on the left of a card and drag it up or down (works with mouse and touch). Ranks renumber automatically and are saved.
- **Colour**: tap the round colour swatch on a card to pick any colour; it colours the card name.
- **Border**: the three small circles pick the box border: grey = none, red, or green.
- New API: `GET/POST /api/ego`, `PATCH/DELETE /api/ego/{id}`, `POST /api/ego/reorder`.
- **Existing database:** run `migration_v6_ego.sql` once in Supabase > SQL Editor (new installs get it from `schema.sql`). Until then the app still loads and shows a notice.

## v7: unfinished tasks roll over to the next day (IST)
- Any task that is **not ticked** on an earlier day is moved to today automatically, the first time you open the app on a new day. Ticked tasks stay on the day they were completed.
- A moved task shows **"Pending · carried over from Nov 11"** so you can tell it is old.
- If you were away for several days, everything unfinished from the last 30 days is pulled to today (change with the `ROLLOVER_DAYS` env var).
- **Time zone is IST (UTC+5:30)** for "today", the date rollover, the greeting, and the habit start date, no matter where the server runs. If the page is left open past midnight IST it refreshes itself.
- Because tasks are *moved*, the earlier day's task count no longer includes them (e.g. Nov 11 shows 0/0 instead of 0/2).
- **Existing database:** run `migration_v7_carry_over.sql` once in Supabase > SQL Editor (adds the `carried_from` column). Without it, roll-over still works, only the "carried over" label is missing.
