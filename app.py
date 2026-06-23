import sqlite3
import hashlib
import hmac
import os
import json
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, g, flash
)

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODEL_PATH = "./model"

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)

labels = {
    0: "A - Важно и срочно",
    1: "В - Важно",
    2: "С - Срочно",
    3: "D - Прочее"
}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

DB_PATH = "database.db"


#  Database 

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            login           TEXT    NOT NULL UNIQUE,
            name            TEXT    NOT NULL,
            password_hash   TEXT    NOT NULL,
            chronotype      TEXT    DEFAULT 'neutral',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title               TEXT    NOT NULL,
            description         TEXT,
            deadline            DATETIME,
            user_estimated_time INTEGER,
            ai_estimated_time   INTEGER,
            priority_quadrant   CHAR(1) CHECK(priority_quadrant IN ('A','B','C','D')),
            difficulty          TEXT    CHECK(difficulty IN ('easy','medium','hard')),
            status              TEXT    DEFAULT 'pending' CHECK(status IN ('pending','done','overdue')),
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at        TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS task_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            actual_time_min INTEGER NOT NULL,
            was_overdue     BOOLEAN DEFAULT 0,
            completed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pomodoro_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            duration    INTEGER NOT NULL,
            completed   BOOLEAN DEFAULT 1,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    db.commit()
    db.close()


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{h}"


def check_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        return hmac.compare_digest(
            hashlib.sha256((salt + password).encode()).hexdigest(), h
        )
    except Exception:
        return False


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()



def ai_classify_importance(title: str, description: str = "") -> dict:
   
    urgent_words = ["срочно", "сегодня", "дедлайн", "горящий", "asap", "urgent"]
    important_words = ["экзамен", "отчёт", "здоровье", "работа", "диплом", "проект"]
    low_words = ["сериал", "соцсети", "игра", "scrolling"]

    text = (title + " " + description).lower()
    is_urgent = any(w in text for w in urgent_words)
    is_important = any(w in text for w in important_words)
    is_low = any(w in text for w in low_words)

    score = 0.4
    if is_important:
        score = 0.8
    if is_low:
        score = 0.2

    if score > 0.6 and is_urgent:
        quadrant = "A"
    elif score > 0.6:
        quadrant = "B"
    elif is_urgent:
        quadrant = "C"
    else:
        quadrant = "D"

    return {"importance_score": round(score, 2), "is_important": score > 0.6, "quadrant": quadrant}





#  Routes — Auth

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    user = current_user()
    today = datetime.now().date()

    tasks_today = db.execute(
        "SELECT * FROM tasks WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 10",
        (user["id"],)
    ).fetchall()

    completed_count = db.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='done'", (user["id"],)
    ).fetchone()[0]

    pending_count = db.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='pending'", (user["id"],)
    ).fetchone()[0]


    ai_tip = "Сегодня сосредоточьтесь на задачах квадранта B — они формируют ваше будущее."

    return render_template(
        "index.html",
        user=user,
        tasks=tasks_today,
        completed_count=completed_count,
        pending_count=pending_count,
        ai_tip=ai_tip,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        login = request.form.get("login", "").strip()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        if not login or not name or not password:
            error = "Заполните все поля"
        elif len(password) < 6:
            error = "Пароль должен содержать минимум 6 символов"
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE login=?", (login,)).fetchone()
            if existing:
                error = "Пользователь с таким логином уже существует"
            else:
                db.execute(
                    "INSERT INTO users (login, name, password_hash) VALUES (?,?,?)",
                    (login, name, hash_password(password))
                )
                db.commit()
                user = db.execute("SELECT * FROM users WHERE login=?", (login,)).fetchone()
                session["user_id"] = user["id"]
                return redirect(url_for("index"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        login_val = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE login=?", (login_val,)).fetchone()
        if not user or not check_password(password, user["password_hash"]):
            error = "Неверный логин или пароль"
        else:
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))



#  Routes — Tasks


@app.route("/tasks")
@login_required
def tasks():
    db = get_db()
    user = current_user()
    quadrant = request.args.get("quadrant", "all")
    status = request.args.get("status", "pending")

    query = "SELECT * FROM tasks WHERE user_id=?"
    params = [user["id"]]

    if quadrant != "all":
        query += " AND priority_quadrant=?"
        params.append(quadrant)
    if status != "all":
        query += " AND status=?"
        params.append(status)

    query += " ORDER BY created_at DESC"
    task_list = db.execute(query, params).fetchall()

    return render_template(
        "tasks.html",
        user=user,
        tasks=task_list,
        selected_quadrant=quadrant,
        selected_status=status,
    )


@app.route("/tasks/create", methods=["GET", "POST"])
@login_required
def create_task():
    user = current_user()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        deadline = request.form.get("deadline") or None
        user_time = request.form.get("user_estimated_time") or None
        difficulty = request.form.get("difficulty", "medium")

        if not title:
            return render_template("task_form.html", user=user, error="Введите название задачи")

   
        ai_result = ai_classify_importance(title, description)
        ai_time = ai_estimate_time(title, difficulty)

        db = get_db()
        db.execute("""
            INSERT INTO tasks
                (user_id, title, description, deadline, user_estimated_time,
                 ai_estimated_time, priority_quadrant, difficulty)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            user["id"], title, description, deadline,
            user_time, ai_time,
            ai_result["quadrant"], difficulty
        ))
        db.commit()
        return redirect(url_for("tasks"))

    return render_template("task_form.html", user=user, task=None, error=None)


@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    user = current_user()
    db = get_db()
    task = db.execute(
        "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user["id"])
    ).fetchone()
    if not task:
        return redirect(url_for("tasks"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        deadline = request.form.get("deadline") or None
        user_time = request.form.get("user_estimated_time") or None
        difficulty = request.form.get("difficulty", "medium")

        if not title:
            return render_template("task_form.html", user=user, task=task, error="Введите название задачи")

        ai_result = ai_classify_importance(title, description)
        ai_time = ai_estimate_time(title, difficulty)

        db.execute("""
            UPDATE tasks SET
                title=?, description=?, deadline=?, user_estimated_time=?,
                ai_estimated_time=?, priority_quadrant=?, difficulty=?
            WHERE id=? AND user_id=?
        """, (
            title, description, deadline, user_time,
            ai_time, ai_result["quadrant"], difficulty,
            task_id, user["id"]
        ))
        db.commit()
        return redirect(url_for("tasks"))

    return render_template("task_form.html", user=user, task=task, error=None)


@app.route("/tasks/<int:task_id>/complete", methods=["POST"])
@login_required
def complete_task(task_id):
    user = current_user()
    db = get_db()
    task = db.execute(
        "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user["id"])
    ).fetchone()
    if task:
        actual_time = request.form.get("actual_time", 0)
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE tasks SET status='done', completed_at=? WHERE id=?",
            (now, task_id)
        )
        if actual_time:
            was_overdue = 0
            if task["deadline"]:
                try:
                    dl = datetime.fromisoformat(task["deadline"])
                    was_overdue = 1 if datetime.now() > dl else 0
                except Exception:
                    pass
            db.execute(
                "INSERT INTO task_history (task_id, user_id, actual_time_min, was_overdue) VALUES (?,?,?,?)",
                (task_id, user["id"], actual_time, was_overdue)
            )
        db.commit()
    return redirect(url_for("tasks"))


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    user = current_user()
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user["id"]))
    db.commit()
    return redirect(url_for("tasks"))



@app.route("/pomodoro")
@login_required
def pomodoro():
    user = current_user()
    db = get_db()
    tasks_list = db.execute(
        "SELECT id, title FROM tasks WHERE user_id=? AND status='pending' ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()
    sessions_today = db.execute(
        "SELECT COUNT(*) FROM pomodoro_sessions WHERE user_id=? AND date(created_at)=date('now')",
        (user["id"],)
    ).fetchone()[0]
    return render_template("pomodoro.html", user=user, tasks=tasks_list, sessions_today=sessions_today)


@app.route("/pomodoro/session", methods=["POST"])
@login_required
def save_pomodoro():
    user = current_user()
    data = request.get_json() or {}
    task_id = data.get("task_id") or None
    duration = data.get("duration", 25)
    completed = data.get("completed", True)

    db = get_db()
    db.execute(
        "INSERT INTO pomodoro_sessions (user_id, task_id, duration, completed) VALUES (?,?,?,?)",
        (user["id"], task_id, duration, 1 if completed else 0)
    )
    db.commit()
    return jsonify({"status": "ok"})



#  Routes — Statistics


@app.route("/stats")
@login_required
def stats():
    user = current_user()
    db = get_db()

    quadrant_data = {}
    for q in ["A", "B", "C", "D"]:
        count = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=? AND priority_quadrant=?",
            (user["id"], q)
        ).fetchone()[0]
        quadrant_data[q] = count

    daily_stats = []
    for i in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        done = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=? AND date(completed_at)=?",
            (user["id"], day)
        ).fetchone()[0]
        daily_stats.append({"date": day, "done": done})

    pomo_stats = db.execute("""
        SELECT date(created_at) as day, COUNT(*) as count
        FROM pomodoro_sessions
        WHERE user_id=? AND date(created_at) >= date('now', '-7 days')
        GROUP BY day ORDER BY day
    """, (user["id"],)).fetchall()

    hourly = db.execute("""
        SELECT strftime('%H', completed_at) as hour, COUNT(*) as count
        FROM tasks
        WHERE user_id=? AND completed_at IS NOT NULL
        GROUP BY hour ORDER BY hour
    """, (user["id"],)).fetchall()

    hourly_data = {str(h).zfill(2): 0 for h in range(24)}
    for row in hourly:
        hourly_data[row["hour"]] = row["count"]

    total_tasks = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=?", (user["id"],)).fetchone()[0]
    total_done = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='done'", (user["id"],)).fetchone()[0]

    return render_template(
        "stats.html",
        user=user,
        quadrant_data=json.dumps(quadrant_data),
        daily_stats=json.dumps(daily_stats),
        pomo_stats=json.dumps([dict(r) for r in pomo_stats]),
        hourly_data=json.dumps(hourly_data),
        total_tasks=total_tasks,
        total_done=total_done,
    )



#  AI API endpoints


@app.route("/ai/estimate_time", methods=["POST"])
@login_required
def api_estimate_time():
    """
    POST body: {"title": str, "difficulty": str}
    Returns:   {"minutes": int}
    """
    data = request.get_json() or {}
    title = data.get("title", "")
    difficulty = data.get("difficulty", "medium")
    minutes = ai_estimate_time(title, difficulty)
    return jsonify({"minutes": minutes})


@app.route("/ai/risk", methods=["POST"])
@login_required
def api_risk():
    """
    POST body: {"task_id": int}
    Returns:   {"probability": float, "message": str}
    """
    data = request.get_json() or {}
    task_id = data.get("task_id")
    user = current_user()
    result = ai_deadline_risk(task_id, user["id"])
    return jsonify(result)


@app.route("/ai/classify", methods=["POST"])
@login_required
def api_classify():
    """
    POST body: {"title": str, "description": str}
    Returns:   {"quadrant": str, "importance_score": float}
    """
    data = request.get_json() or {}
    result = predict_task(data.get("title", ""))
    variance = 0
    quad = ""
    for q, val in result.items():
        if variance < val:
            variance = val
            quad = q
    return jsonify({"quadrant":quad[0], "importance": quad[2:]})



def predict_task(text):

    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=64
    )

    with torch.no_grad():
        outputs = model(**inputs)

    probs = torch.softmax(outputs.logits, dim=1)[0]

    result = {}

    for idx, prob in enumerate(probs):
        result[labels[idx]] = round(prob.item(), 4)

    return result



if __name__ == "__main__":
    init_db()
    app.run(debug=True)
