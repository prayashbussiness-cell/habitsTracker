"""Start Your Day: FastAPI + Supabase backend (also serves the frontend in /static).

Run:  pip install -r requirements.txt && uvicorn main:app --reload   ->  http://127.0.0.1:8000
"""
import calendar, hashlib, hmac, logging, os, re
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

URL, KEY, SECRET = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"), os.getenv("APP_SECRET")
if not (URL and KEY and SECRET):
    raise RuntimeError("Set SUPABASE_URL, SUPABASE_KEY and APP_SECRET (see .env.example).")
if not URL.startswith("http"):
    URL = "https://" + URL
sb: Client = create_client(URL, KEY)

CATS = ["Work", "Health & Fitness", "Learning", "Personal", "Finance", "Other"]
app = FastAPI(title="Start Your Day API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- helpers ----------
def run(query):
    try:
        return query.execute().data
    except Exception as exc:  # noqa: BLE001
        log.error("Supabase error: %s", exc)
        raise HTTPException(502, f"Database error: {exc}") from exc


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
    d = date.fromisoformat(str(d))
    row = history(uid, d, d)[0]
    row.pop("date")
    run(sb.table("daily_statistics").upsert({"user_id": uid, "stat_date": d.isoformat(), **row}, on_conflict="user_id,stat_date"))


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


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"), html=True), name="static")
