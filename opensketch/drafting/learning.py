"""Module J: plans, feedback, approved examples and company guidelines, kept per account.

One SQLite file per account in the data folder (data_dir()/drafting/<account>/drafting.sqlite). Nothing leaves the
server, nothing trains an external model. A feedback record always keeps what was decided and when; the plan and
the drawing details are kept as a training example only when the person says so (`retain`). Approved expert
examples are separated from unverified user edits by the reviewer role and the kind of feedback.

Expert reviews (the real-drawing benchmark, apart from the 12 synthetic cases in benchmarks.py): a drawing is
submitted for review with the engine's own check at that moment (status awaiting_expert); only an expert verdict
(expert_approve or expert_reject, reviewer "expert", with the reviewer's name) makes it expert_reviewed. The
summary measures how much a person corrected before the verdict and where the engine's check and the expert
disagreed. BIZOMAT does not verify a reviewer's qualifications: a review is recorded as stated by the named reviewer.
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
         "guideline": "a company drafting guideline", "answers": "answers to the plan's questions",
         "submit_for_review": "the drawing is submitted for an expert's review"}
CORRECTIONS = ("edit_dimensions", "change_views", "move_annotation", "change_notes", "reject")
EXPERT_KINDS = ("expert_approve", "expert_reject")
REVIEW_LABEL = ("expert-reviewed drawings: verdicts as stated by the named reviewer through the AI app; BIZOMAT does not "
                "verify reviewers' qualifications. Kept apart from the synthetic benchmark cases.")

SCHEMA = """
create table if not exists plans (id text primary key, at real, model_title text, model_doc text, model_stamp text,
  disciplines text, plan text);
create table if not exists feedback (id integer primary key autoincrement, at real, plan_id text, drawing text, kind text,
  target text, before text, after text, comment text, reviewer text, retain integer, model_stamp text, snapshot text);
create table if not exists guidelines (id text primary key, at real, entry text, reviewer text);
create table if not exists reviews (plan_id text primary key, at real, drawing text, model_title text, engine_quality integer,
  engine_blocked integer, engine_blockers text, status text, verdict text, reviewer_name text, expert_score integer,
  comment text, reviewed_at real, corrections integer);
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
                    reviewer: str = "user", retain: bool = False, model_stamp: Any = None,
                    reviewer_name: str | None = None, expert_score: int | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    if reviewer not in ("user", "expert"):
        raise ValueError("reviewer is user or expert")
    if kind in EXPERT_KINDS and (reviewer != "expert" or not (reviewer_name or "").strip()):
        raise ValueError(f"{kind} is an expert's verdict: reviewer must be expert and reviewer_name the reviewer's name "
                         "(a person's own approval is kind=accept)")
    if expert_score is not None and not (isinstance(expert_score, int) and 0 <= expert_score <= 100):
        raise ValueError("expert_score is a whole number from 0 to 100")
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
    out = {"feedback_id": fid, "kind": kind, "meaning": KINDS[kind], "reviewer": reviewer, "retained_as_example": bool(retain and snapshot),
           "status": "approved expert example" if (kind == "expert_approve" and reviewer == "expert" and retain) else
                     "unverified user feedback" if reviewer == "user" else "expert feedback"}
    if kind in EXPERT_KINDS and plan_id:
        out["review"] = _close_review(account, plan_id, kind, reviewer_name, expert_score, comment)
    return out


def submit_review(account: str | None, plan_id: str, drawing: str | None, report: dict) -> dict:
    """A drawing put forward for an expert's review, with the engine's own check of it at that moment."""
    p = get_plan(account, plan_id)
    if p is None:
        raise ValueError(f"No plan {plan_id}.")
    blockers = [f.get("message") for f in report.get("release_blockers") or []][:30]
    with closing(_conn(account)) as c, c:
        old = c.execute("select status from reviews where plan_id = ?", (plan_id,)).fetchone()
        if old and old[0] == "expert_reviewed":
            raise ValueError(f"The drawing of plan {plan_id} was already reviewed by an expert; plan and build again for a new review.")
        c.execute("insert or replace into reviews (plan_id, at, drawing, model_title, engine_quality, engine_blocked, engine_blockers, "
                  "status) values (?,?,?,?,?,?,?,?)",
                  (plan_id, time.time(), drawing, p["model"].get("title"), report.get("quality_index"),
                   int(bool(report.get("release_blocked"))), json.dumps(blockers), "awaiting_expert"))
    return review(account, plan_id)


def _close_review(account, plan_id, kind, reviewer_name, expert_score, comment) -> dict | None:
    with closing(_conn(account)) as c, c:
        row = c.execute("select at, status from reviews where plan_id = ?", (plan_id,)).fetchone()
        if row is None:
            return None
        n = c.execute(f"select count(*) from feedback where plan_id = ? and reviewer = 'user' and kind in ({','.join('?' * len(CORRECTIONS))})",
                      (plan_id, *CORRECTIONS)).fetchone()[0]
        c.execute("update reviews set status = 'expert_reviewed', verdict = ?, reviewer_name = ?, expert_score = ?, comment = ?, "
                  "reviewed_at = ?, corrections = ? where plan_id = ?",
                  ("approved" if kind == "expert_approve" else "rejected", (reviewer_name or "").strip()[:80], expert_score,
                   (comment or "")[:2000], time.time(), n, plan_id))
    return review(account, plan_id)


def _agreement(engine_blocked: bool, verdict: str | None) -> str | None:
    if verdict is None:
        return None
    if verdict == "approved":
        return "engine stricter" if engine_blocked else "agree"
    return "agree" if engine_blocked else "engine missed problems"


def review(account: str | None, plan_id: str) -> dict | None:
    with closing(_conn(account)) as c:
        r = c.execute("select plan_id, at, drawing, model_title, engine_quality, engine_blocked, engine_blockers, status, verdict, "
                      "reviewer_name, expert_score, comment, reviewed_at, corrections from reviews where plan_id = ?", (plan_id,)).fetchone()
    if r is None:
        return None
    return {"plan_id": r[0], "submitted": r[1], "drawing": r[2], "model": r[3],
            "engine": {"quality_index": r[4], "release_blocked": bool(r[5]), "release_blockers": json.loads(r[6] or "[]")},
            "status": r[7], "verdict": r[8], "reviewer_name": r[9], "expert_score": r[10], "comment": r[11], "reviewed": r[12],
            "corrections_before_verdict": r[13], "agreement": _agreement(bool(r[5]), r[8]),
            "label": REVIEW_LABEL if r[7] == "expert_reviewed" else "awaiting an expert's review: not expert-reviewed"}


def review_summary(account: str | None) -> dict[str, Any]:
    """The real-drawing benchmark: counts, approval, corrections before the verdict, agreement with the engine."""
    with closing(_conn(account)) as c:
        rows = c.execute("select status, verdict, engine_blocked, corrections, engine_quality, expert_score from reviews").fetchall()
    done = [r for r in rows if r[0] == "expert_reviewed"]
    agree: dict[str, int] = {}
    for r in done:
        k = _agreement(bool(r[2]), r[1])
        agree[k] = agree.get(k, 0) + 1
    scored = [(r[4], r[5]) for r in done if r[4] is not None and r[5] is not None]
    return {"label": REVIEW_LABEL, "awaiting_expert": sum(1 for r in rows if r[0] == "awaiting_expert"),
            "expert_reviewed": len(done), "approved": sum(1 for r in done if r[1] == "approved"),
            "rejected": sum(1 for r in done if r[1] == "rejected"),
            "mean_corrections_before_verdict": round(sum(r[3] or 0 for r in done) / len(done), 2) if done else None,
            "agreement_with_engine": agree,
            "mean_score_gap": round(sum(e - x for e, x in scored) / len(scored), 1) if scored else None,
            "score_gap_basis": "engine quality index minus the expert's score, where the expert gave one"}


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
    return {"plans": plans, "feedback": kinds, "approved_examples": approved, "guidelines": g, "reviews": review_summary(account)}
