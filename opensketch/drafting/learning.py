"""Module J: plans, feedback, approved examples and company guidelines, kept per account.

One SQLite file per account in the data folder (data_dir()/drafting/<account>/drafting.sqlite). Nothing leaves the
server, nothing trains an external model. A feedback record always keeps what was decided and when; the plan and
the drawing details are kept as a training example only when the person says so (`retain`). Approved expert
examples are separated from unverified user edits by the reviewer role and the kind of feedback.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .. import store

KINDS = {"accept": "user accepts the recommendation", "reject": "user rejects the recommendation",
         "edit_dimensions": "user edited dimensions", "change_views": "user changed the view selection",
         "move_annotation": "user corrected annotation placement", "change_notes": "user changed manufacturing notes",
         "expert_approve": "an expert approves the final drawing", "expert_reject": "an expert rejects the final drawing",
         "guideline": "a company drafting guideline", "answers": "answers to the plan's questions"}

SCHEMA = """
create table if not exists plans (id text primary key, at real, model_title text, model_doc text, model_stamp text,
  disciplines text, plan text);
create table if not exists feedback (id integer primary key autoincrement, at real, plan_id text, drawing text, kind text,
  target text, before text, after text, comment text, reviewer text, retain integer, model_stamp text, snapshot text);
create table if not exists guidelines (id text primary key, at real, entry text, reviewer text);
"""


def _safe(name: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name or "local")[:64] or "local"


def db_path(account: str | None) -> Path:
    d = store.data_dir() / "drafting" / _safe(account)
    d.mkdir(parents=True, exist_ok=True)
    return d / "drafting.sqlite"


def _conn(account: str | None) -> sqlite3.Connection:
    c = sqlite3.connect(db_path(account), timeout=10)
    c.executescript(SCHEMA)
    return c


def save_plan(account: str | None, plan: dict, stamp: Any = None) -> None:
    store.check_disk(len(json.dumps(plan)))
    with closing(_conn(account)) as c, c:
        c.execute("insert or replace into plans values (?,?,?,?,?,?,?)",
                  (plan["plan_id"], plan["created"], plan["model"].get("title"), plan["model"].get("doc"),
                   None if stamp is None else str(stamp), json.dumps(plan["disciplines"]), json.dumps(plan)))


def get_plan(account: str | None, plan_id: str) -> dict | None:
    with closing(_conn(account)) as c:
        row = c.execute("select plan from plans where id = ?", (plan_id,)).fetchone()
    return json.loads(row[0]) if row else None


def record_feedback(account: str | None, kind: str, *, plan_id: str | None = None, drawing: str | None = None,
                    target: str | None = None, before: Any = None, after: Any = None, comment: str | None = None,
                    reviewer: str = "user", retain: bool = False, model_stamp: Any = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    if reviewer not in ("user", "expert"):
        raise ValueError("reviewer is user or expert")
    snapshot = None
    if retain and plan_id:
        p = get_plan(account, plan_id)
        snapshot = json.dumps(p) if p else None
    rec = (time.time(), plan_id, drawing, kind, target, json.dumps(before) if before is not None else None,
           json.dumps(after) if after is not None else None, (comment or "")[:2000], reviewer, int(bool(retain)),
           None if model_stamp is None else str(model_stamp), snapshot)
    store.check_disk(sum(len(str(x or "")) for x in rec))
    with closing(_conn(account)) as c, c:
        cur = c.execute("insert into feedback (at, plan_id, drawing, kind, target, before, after, comment, reviewer, retain, "
                        "model_stamp, snapshot) values (?,?,?,?,?,?,?,?,?,?,?,?)", rec)
        fid = cur.lastrowid
    return {"feedback_id": fid, "kind": kind, "meaning": KINDS[kind], "reviewer": reviewer, "retained_as_example": bool(retain and snapshot),
            "status": "approved expert example" if (kind == "expert_approve" and reviewer == "expert" and retain) else
                      "unverified user feedback" if reviewer == "user" else "expert feedback"}


def add_guideline(account: str | None, entry: dict, reviewer: str = "user") -> dict:
    """A company guideline: level 'company' when the reviewer is an expert (the owner's verified practice), else a
    'suggestion' awaiting verification. Never 'mandatory' from here: that needs the owner's verified entry file."""
    from . import knowledge
    e = dict(entry)
    e.setdefault("id", "C-" + str(int(time.time() * 1000))[-9:])
    e.setdefault("category", "15")
    e["level"] = "company" if reviewer == "expert" else "suggestion"
    e["validation"] = "reviewed" if reviewer == "expert" else "unverified"
    e.setdefault("source", {"type": "company guideline", "note": f"entered by {reviewer}"})
    e["created"] = time.time()
    e["reviewer"] = reviewer
    norm = knowledge.normalise(e, "company")
    with closing(_conn(account)) as c, c:
        c.execute("insert or replace into guidelines values (?,?,?,?)", (norm["id"], norm["created"], json.dumps(norm), reviewer))
    return norm


def guidelines(account: str | None) -> list[dict]:
    with closing(_conn(account)) as c:
        rows = c.execute("select entry from guidelines order by at").fetchall()
    return [json.loads(r[0]) for r in rows]


def examples(account: str | None, approved_only: bool = True) -> list[dict]:
    q = "select plan_id, kind, reviewer, comment, at from feedback where retain = 1"
    if approved_only:
        q += " and kind = 'expert_approve' and reviewer = 'expert'"
    with closing(_conn(account)) as c:
        rows = c.execute(q + " order by at").fetchall()
    return [{"plan_id": r[0], "kind": r[1], "reviewer": r[2], "comment": r[3], "at": r[4]} for r in rows]


def stats(account: str | None) -> dict[str, Any]:
    with closing(_conn(account)) as c:
        kinds = dict(c.execute("select kind, count(*) from feedback group by kind").fetchall())
        plans = c.execute("select count(*) from plans").fetchone()[0]
        approved = c.execute("select count(*) from feedback where kind='expert_approve' and reviewer='expert' and retain=1").fetchone()[0]
        g = c.execute("select count(*) from guidelines").fetchone()[0]
    return {"plans": plans, "feedback": kinds, "approved_examples": approved, "guidelines": g}
