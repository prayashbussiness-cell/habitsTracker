"""Start Your Day: FastAPI + Supabase backend (also serves the frontend in /static).

Run:  pip install -r requirements.txt && uvicorn main:app --reload   ->  http://127.0.0.1:8000
"""
import calendar, hashlib, hmac, logging, os, re, threading, time
from datetime import date, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from supabase import Client, create_client

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("start-your-day")

URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
KEY = (os.getenv("SUPABASE_KEY") or "").strip()
missing = [n for n, v in (("SUPABASE_URL", URL), ("SUPABASE_KEY", KEY)) if not v]
if missing:
    raise RuntimeError("Missing environment variables: " + ", ".join(missing))
if "your-project" in URL:
    raise RuntimeError("SUPABASE_URL is still the placeholder. Paste your real Project URL from Supabase.")
if KEY.startswith("sb_publishable"):
    raise RuntimeError("SUPABASE_KEY is the publishable key. Use the SECRET key (sb_secret_...) from Supabase > Settings > API Keys.")
if not URL.startswith("http"):
    URL = "https://" + URL
# APP_SECRET is optional: if you do not set it, a secret is derived from SUPABASE_KEY (never exposed to the browser).
SECRET = (os.getenv("APP_SECRET") or "").strip() or hashlib.sha256(("start-your-day:" + KEY).encode()).hexdigest()


# ---------- Supabase access (thread-safe, auto-retrying) ----------
# Why: FastAPI runs every sync endpoint in a thread pool. Sharing ONE supabase/httpx client between those
# threads (the browser fires several requests at once) causes "[Errno 11] Resource temporarily unavailable".
# Fix: one client per thread, and a failed call is retried on a brand-new client before we give up.
try:
    from postgrest.exceptions import APIError  # real SQL/permission errors: never retry these
except Exception:  # noqa: BLE001
    class APIError(Exception):  # type: ignore[no-redef]
        pass

_local = threading.local()


def _client() -> Client:
    if getattr(_local, "c", None) is None:
        _local.c = create_client(URL, KEY)
    return _local.c


def _reset_client() -> None:
    _local.c = None


class Q:
    """Records a query chain (sb.table(..).select(..).eq(..)) and replays it on execute(), so a retry can
    rebuild the whole query on a fresh client instead of re-using a broken connection."""

    def __init__(self, ops=()):
        self._ops = tuple(ops)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: Q(self._ops + ((name, a, k),))

    def execute(self, attempts: int = 4):
        last = None
        for i in range(attempts):
            try:
                obj = _client()
                for name, a, k in self._ops:
                    obj = getattr(obj, name)(*a, **k)
                return obj.execute()
            except APIError:
                raise
            except Exception as exc:  # noqa: BLE001  (network / socket / pool errors)
                last = exc
                log.warning("Supabase call failed (try %d/%d): %s", i + 1, attempts, exc)
                _reset_client()
                time.sleep(0.25 * (i + 1))
        raise last  # type: ignore[misc]


sb = Q()

CATS = ["Work", "Health & Fitness", "Learning", "Personal", "Finance", "Other"]
app = FastAPI(title="Start Your Day API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
    return resp


# ---------- helpers ----------
def run(query):
    try:
        return query.execute().data
    except Exception as exc:  # noqa: BLE001
        log.error("Supabase error: %s", exc)
        raise HTTPException(502, "Database is busy, please try again in a moment.") from exc


def norm_phone(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) != 10:
        raise ValueError("Enter a 10-digit phone number.")
    return d


def sign(uid: str) -> str:
    return f"{uid}.{hmac.new(SECRET.encode(), uid.encode(), hashlib.sha256).hexdigest()}"


def current_user(authorization: Optional[str] = Header(None)) -> str:
    if authorization and authorization.startswith("Bearer "):
        uid, _, sig = authorization[7:].partition(".")
        good = hmac.new(SECRET.encode(), uid.encode(), hashlib.sha256).hexdigest()
        if uid and hmac.compare_digest(sig, good):
            return uid
    raise HTTPException(401, "Please log in again.")


def pct(x: float) -> int:
    return int(x * 100 + 0.5)


def calc(tasks, cards, prog) -> dict:
    """Daily efficiency = average of task completion and mean habit progress.
    Skipped habits are excluded; a part with nothing to count is ignored."""
    n, td = len(tasks), sum(1 for t in tasks if t["done"])
    act = [c for c in cards if not prog.get(c["id"], {}).get("skipped")]
    ratios = [min(1.0, float(prog.get(c["id"], {}).get("actual") or 0) / float(c["target"])) for c in act]
    parts = ([td / n] if n else []) + ([sum(ratios) / len(ratios)] if ratios else [])
    return dict(tasks_done=td, tasks_total=n, habits_done=sum(1 for r in ratios if r >= 1),
                habits_total=len(act), habits_skipped=len(cards) - len(act),
                task_pct=pct(td / n) if n else 0, efficiency=pct(sum(parts) / len(parts)) if parts else 0)


def history(uid: str, start: date, end: date) -> list:
    s, e = start.isoformat(), end.isoformat()
    tasks = run(sb.table("daily_tasks").select("task_date,done").eq("user_id", uid).gte("task_date", s).lte("task_date", e))
    cards = run(sb.table("habit_cards").select("id,target,starts_on").eq("user_id", uid))
    prog = run(sb.table("daily_habit_progress").select("card_id,progress_date,actual,skipped").eq("user_id", uid).gte("progress_date", s).lte("progress_date", e))
    out, d = [], start
    while d <= end:
        iso = d.isoformat()
        out.append({"date": iso, **calc([t for t in tasks if t["task_date"] == iso],
                                        [c for c in cards if c["starts_on"] <= iso],
                                        {p["card_id"]: p for p in prog if p["progress_date"] == iso})})
        d += timedelta(days=1)
    return out


def recompute(uid: str, d) -> None:
    """Refresh the stored daily statistics. Best effort: the task/habit change is already saved, so a
    hiccup here must not turn a successful save into an error."""
    try:
        d = date.fromisoformat(str(d))
        row = history(uid, d, d)[0]
        row.pop("date")
        run(sb.table("daily_statistics").upsert({"user_id": uid, "stat_date": d.isoformat(), **row}, on_conflict="user_id,stat_date"))
    except Exception as exc:  # noqa: BLE001
        log.error("recompute failed for %s: %s", d, exc)


# ---------- schemas ----------
class AuthIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    phone: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, v):
        v = re.sub(r"[<>\"&]", "", v).strip()
        if len(v) < 2:
            raise ValueError("Enter your name.")
        return v

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v):
        return norm_phone(v)


class TaskIn(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=200)
    category: str = "Other"
    priority: str = Field("med", pattern="^(high|med|low)$")
    description: Optional[str] = None


class TaskPatch(BaseModel):
    done: bool


class CardIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = "Other"
    target: float = Field(gt=0)
    unit: str = Field("hour", min_length=1, max_length=30)
    icon: str = "book"
    description: Optional[str] = None


class ProgressIn(BaseModel):
    card_id: str
    date: date
    actual: float = Field(0, ge=0)
    note: Optional[str] = ""
    skipped: bool = False


class NoteIn(BaseModel):
    date: date
    note: str = ""


class GoalIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    progress: int = Field(0, ge=0, le=100)


# ---------- auth ----------
@app.post("/api/auth/signup")
def signup(b: AuthIn):
    if run(sb.table("users").select("id").eq("phone", b.phone)):
        raise HTTPException(409, "This number already has an account. Log in instead.")
    u = run(sb.table("users").insert({"name": b.name, "phone": b.phone}))[0]
    return {"token": sign(u["id"]), "user": {"name": u["name"], "phone": u["phone"]}}


@app.post("/api/auth/login")
def login(b: AuthIn):
    rows = run(sb.table("users").select("*").eq("phone", b.phone))
    if not rows or rows[0]["name"].lower() != b.name.lower():
        raise HTTPException(401, "Name and phone number do not match an account. Sign up first.")
    return {"token": sign(rows[0]["id"]), "user": {"name": rows[0]["name"], "phone": rows[0]["phone"]}}


@app.get("/api/me")
def me(uid: str = Depends(current_user)):
    rows = run(sb.table("users").select("name,phone").eq("id", uid))
    if not rows:
        raise HTTPException(401, "Please log in again.")
    return rows[0]


# ---------- day view ----------
@app.get("/api/day")
def get_day(d: Optional[date] = Query(None, alias="date"), uid: str = Depends(current_user)):
    iso = (d or date.today()).isoformat()
    tasks = run(sb.table("daily_tasks").select("id,name,category,priority,done").eq("user_id", uid).eq("task_date", iso).order("created_at"))
    prog = run(sb.table("daily_habit_progress").select("card_id,actual,note,skipped").eq("user_id", uid).eq("progress_date", iso))
    note = run(sb.table("daily_notes").select("note").eq("user_id", uid).eq("note_date", iso))
    return {"date": iso, "tasks": tasks, "progress": {p["card_id"]: p for p in prog}, "note": note[0]["note"] if note else ""}


@app.get("/api/history")
def get_history(days: int = Query(14, ge=1, le=60), uid: str = Depends(current_user)):
    return history(uid, date.today() - timedelta(days=days - 1), date.today())


# ---------- tasks ----------
@app.post("/api/tasks")
def add_task(b: TaskIn, uid: str = Depends(current_user)):
    row = run(sb.table("daily_tasks").insert({"user_id": uid, "task_date": b.date.isoformat(), "name": b.name.strip(),
              "category": b.category, "priority": b.priority, "description": b.description}))[0]
    recompute(uid, b.date)
    return row


def own_task(uid, tid):
    rows = run(sb.table("daily_tasks").select("id,task_date").eq("id", tid).eq("user_id", uid))
    if not rows:
        raise HTTPException(404, "Task not found.")
    return rows[0]


@app.patch("/api/tasks/{tid}")
def toggle_task(tid: str, b: TaskPatch, uid: str = Depends(current_user)):
    t = own_task(uid, tid)
    run(sb.table("daily_tasks").update({"done": b.done}).eq("id", tid))
    recompute(uid, t["task_date"])
    return {"status": "ok"}


@app.delete("/api/tasks/{tid}")
def delete_task(tid: str, uid: str = Depends(current_user)):
    t = own_task(uid, tid)
    run(sb.table("daily_tasks").delete().eq("id", tid))
    recompute(uid, t["task_date"])
    return {"status": "ok"}


# ---------- habit cards (one-time setup, shown every day) ----------
@app.get("/api/cards")
def list_cards(uid: str = Depends(current_user)):
    return run(sb.table("habit_cards").select("*").eq("user_id", uid).order("created_at"))


@app.post("/api/cards")
def add_card(b: CardIn, uid: str = Depends(current_user)):
    row = run(sb.table("habit_cards").insert({"user_id": uid, **b.model_dump(), "starts_on": date.today().isoformat()}))[0]
    recompute(uid, date.today())
    return row


@app.put("/api/cards/{cid}")
def edit_card(cid: str, b: CardIn, uid: str = Depends(current_user)):
    rows = run(sb.table("habit_cards").update(b.model_dump()).eq("id", cid).eq("user_id", uid))
    if not rows:
        raise HTTPException(404, "Card not found.")
    recompute(uid, date.today())
    return rows[0]


@app.delete("/api/cards/{cid}")
def delete_card(cid: str, uid: str = Depends(current_user)):
    run(sb.table("habit_cards").delete().eq("id", cid).eq("user_id", uid))
    recompute(uid, date.today())
    return {"status": "ok"}


@app.put("/api/progress")
def put_progress(b: ProgressIn, uid: str = Depends(current_user)):
    if not run(sb.table("habit_cards").select("id").eq("id", b.card_id).eq("user_id", uid)):
        raise HTTPException(404, "Card not found.")
    run(sb.table("daily_habit_progress").upsert({"user_id": uid, "card_id": b.card_id, "progress_date": b.date.isoformat(),
        "actual": b.actual, "note": b.note or "", "skipped": b.skipped}, on_conflict="card_id,progress_date"))
    recompute(uid, b.date)
    return {"status": "ok"}


@app.put("/api/notes")
def put_note(b: NoteIn, uid: str = Depends(current_user)):
    run(sb.table("daily_notes").upsert({"user_id": uid, "note_date": b.date.isoformat(), "note": b.note}, on_conflict="user_id,note_date"))
    return {"status": "ok"}


# ---------- goals ----------
@app.get("/api/goals")
def list_goals(uid: str = Depends(current_user)):
    return run(sb.table("goals").select("*").eq("user_id", uid).order("created_at"))


@app.post("/api/goals")
def add_goal(b: GoalIn, uid: str = Depends(current_user)):
    if not b.name:
        raise HTTPException(422, "Goal name is required.")
    return run(sb.table("goals").insert({"user_id": uid, "name": b.name.strip(), "progress": b.progress}))[0]


@app.put("/api/goals/{gid}")
def edit_goal(gid: str, b: GoalIn, uid: str = Depends(current_user)):
    patch = {"progress": b.progress, **({"name": b.name} if b.name else {})}
    run(sb.table("goals").update(patch).eq("id", gid).eq("user_id", uid))
    return {"status": "ok"}


@app.delete("/api/goals/{gid}")
def delete_goal(gid: str, uid: str = Depends(current_user)):
    run(sb.table("goals").delete().eq("id", gid).eq("user_id", uid))
    return {"status": "ok"}


# ---------- monthly / yearly / streak / categories ----------
@app.get("/api/summary")
def summary(uid: str = Depends(current_user)):
    today = date.today()
    rows = run(sb.table("daily_statistics").select("*").eq("user_id", uid).gte("stat_date", date(today.year, 1, 1).isoformat()).order("stat_date"))
    act = [r for r in rows if r["tasks_total"] or r["habits_total"]]
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else 0  # noqa: E731
    habit_pct = lambda rs: avg([r["habits_done"] / r["habits_total"] * 100 for r in rs if r["habits_total"]])  # noqa: E731
    mo = [r for r in act if r["stat_date"][:7] == today.strftime("%Y-%m")]
    goal_pct = avg([g["progress"] for g in run(sb.table("goals").select("progress").eq("user_id", uid))])
    months = [avg([r["efficiency"] for r in act if int(r["stat_date"][5:7]) == m]) for m in range(1, 13)]

    ok = sorted(date.fromisoformat(r["stat_date"]) for r in act if r["efficiency"] >= 50)
    best = run_len = 0
    prev = None
    for d in ok:
        run_len = run_len + 1 if prev and (d - prev).days == 1 else 1
        best, prev = max(best, run_len), d
    okset, cur = set(ok), 0
    d = today if today in okset else today - timedelta(days=1)
    while d in okset:
        cur, d = cur + 1, d - timedelta(days=1)

    since = (today - timedelta(days=29)).isoformat()
    buckets: dict = {}
    for t in run(sb.table("daily_tasks").select("category,done").eq("user_id", uid).gte("task_date", since)):
        buckets.setdefault(t["category"], []).append(1 if t["done"] else 0)
    cards = {c["id"]: c for c in run(sb.table("habit_cards").select("id,category,target").eq("user_id", uid))}
    for p in run(sb.table("daily_habit_progress").select("card_id,actual,skipped").eq("user_id", uid).gte("progress_date", since)):
        c = cards.get(p["card_id"])
        if c and not p["skipped"]:
            buckets.setdefault(c["category"], []).append(min(1.0, float(p["actual"] or 0) / float(c["target"])))
    cats = sorted(([k, pct(sum(v) / len(v))] for k, v in buckets.items()), key=lambda x: -x[1])

    return {
        "month": {"avg": avg([r["efficiency"] for r in mo]), "tasks_done": sum(r["tasks_done"] for r in mo),
                  "tasks_total": sum(r["tasks_total"] for r in mo), "habits_pct": habit_pct(mo), "goals_pct": goal_pct},
        "year": {"avg": avg([r["efficiency"] for r in act]), "tasks": sum(r["tasks_done"] for r in act),
                 "habits": sum(r["habits_done"] for r in act), "goals_pct": goal_pct, "months": months,
                 "best_month": calendar.month_name[months.index(max(months)) + 1] if any(months) else None},
        "streak": {"current": cur, "best": best},
        "categories": cats,
    }


# ---------- ideas ----------
class IdeaIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    details: Optional[str] = Field("", max_length=2000)
    time_required: Optional[str] = Field("", max_length=100)
    advantage: Optional[str] = Field("", max_length=1000)


class IdeaSkip(BaseModel):
    skipped: bool


def idea_row(b: IdeaIn) -> dict:
    return {"name": b.name.strip(), "details": (b.details or "").strip(),
            "time_required": (b.time_required or "").strip(), "advantage": (b.advantage or "").strip()}


@app.get("/api/ideas")
def list_ideas(uid: str = Depends(current_user)):
    return run(sb.table("ideas").select("*").eq("user_id", uid).order("created_at"))


@app.post("/api/ideas")
def add_idea(b: IdeaIn, uid: str = Depends(current_user)):
    return run(sb.table("ideas").insert({"user_id": uid, **idea_row(b)}))[0]


@app.put("/api/ideas/{iid}")
def edit_idea(iid: str, b: IdeaIn, uid: str = Depends(current_user)):
    rows = run(sb.table("ideas").update(idea_row(b)).eq("id", iid).eq("user_id", uid))
    if not rows:
        raise HTTPException(404, "Idea not found.")
    return rows[0]


@app.patch("/api/ideas/{iid}/skip")
def skip_idea(iid: str, b: IdeaSkip, uid: str = Depends(current_user)):
    rows = run(sb.table("ideas").update({"skipped": b.skipped}).eq("id", iid).eq("user_id", uid))
    if not rows:
        raise HTTPException(404, "Idea not found.")
    return {"status": "ok"}


@app.delete("/api/ideas/{iid}")
def delete_idea(iid: str, uid: str = Depends(current_user)):
    run(sb.table("ideas").delete().eq("id", iid).eq("user_id", uid))
    return {"status": "ok"}


# ---------- body condition (mood index + body strength, 0-10 each, one row per day) ----------
class ConditionIn(BaseModel):
    date: date
    mood: Optional[int] = Field(None, ge=0, le=10)
    body_strength: Optional[int] = Field(None, ge=0, le=10)


@app.get("/api/condition")
def get_condition(d: Optional[date] = Query(None, alias="date"), days: int = Query(30, ge=1, le=366),
                  uid: str = Depends(current_user)):
    q = sb.table("body_condition").select("log_date,mood,body_strength").eq("user_id", uid)
    q = q.eq("log_date", d.isoformat()) if d else q.gte("log_date", (date.today() - timedelta(days=days - 1)).isoformat())
    return run(q.order("log_date"))


@app.put("/api/condition")
def put_condition(b: ConditionIn, uid: str = Depends(current_user)):
    vals = {k: v for k, v in (("mood", b.mood), ("body_strength", b.body_strength)) if v is not None}
    if not vals:
        raise HTTPException(422, "Choose a mood or body strength value.")
    run(sb.table("body_condition").upsert({"user_id": uid, "log_date": b.date.isoformat(), **vals}, on_conflict="user_id,log_date"))
    return {"status": "ok"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"), html=True), name="static")
