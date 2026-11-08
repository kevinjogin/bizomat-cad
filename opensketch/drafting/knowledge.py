"""Module D: the drafting knowledge base and its retrieval.

Shipped entries live in knowledge/*.json (versioned with the code). Company entries (the owner's own drafting
guidelines) and suggestions awaiting verification live per account in the data folder (learning.py). Every entry
has the same structured fields, a level and a validation status:

  level       mandatory    a verified engineering requirement (only the owner can mark an entry so)
              recommended  recommended drafting practice (all shipped entries)
              company      a company-specific preference, entered by the owner
              example      an illustrative example (synthetic unless marked approved)
              suggestion   an AI or user suggestion awaiting verification (excluded from retrieval by default)
  validation  unverified | reviewed | verified

Retrieval is BM25 over the entry's text with boosts for the requested discipline and topic, and returns why each
entry matched (the terms), so the AI can explain a recommendation and cite its source.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent / "knowledge"
LEVELS = ("mandatory", "recommended", "company", "example", "suggestion")
VALIDATION = ("unverified", "reviewed", "verified")
FIELDS = ("id", "category", "topic", "disciplines", "concept", "explanation", "practice", "example", "correct", "mistake",
          "standards", "tags")
DEFAULT_SOURCE = {"type": "BIZOMAT drafting guide",
                  "note": "written for BIZOMAT from general engineering drafting practice; no text of any standard reproduced"}
STOP = set("a an the of to in on for and or is are be by with from as at it its this that each every one not no".split())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9&]+", text.lower()) if t not in STOP and len(t) > 1]


def normalise(e: dict, origin: str) -> dict:
    """An entry with every field, its defaults, and checks; raises ValueError on a malformed entry."""
    missing = [f for f in ("id", "category", "topic", "concept", "practice") if not e.get(f)]
    if missing:
        raise ValueError(f"knowledge entry {e.get('id', '?')}: missing {', '.join(missing)}")
    out = {f: e.get(f) for f in FIELDS}
    out["disciplines"] = list(e.get("disciplines") or ["*"])
    out["standards"] = [{"ref": s.get("ref"), "edition": s.get("edition"), "verified": bool(s.get("verified", False))}
                        for s in (e.get("standards") or []) if isinstance(s, dict) and s.get("ref")]
    out["tags"] = list(e.get("tags") or [])
    out["level"] = e.get("level") or "recommended"
    if out["level"] not in LEVELS:
        raise ValueError(f"knowledge entry {out['id']}: level must be one of {', '.join(LEVELS)}")
    out["validation"] = e.get("validation") or "unverified"
    if out["validation"] not in VALIDATION:
        raise ValueError(f"knowledge entry {out['id']}: validation must be one of {', '.join(VALIDATION)}")
    if out["level"] == "mandatory" and out["validation"] != "verified":
        raise ValueError(f"knowledge entry {out['id']}: a mandatory requirement must be verified")
    out["confidence"] = e.get("confidence") or "medium"
    out["source"] = e.get("source") or DEFAULT_SOURCE
    out["origin"] = origin
    for k in ("created", "reviewer", "updated"):
        if e.get(k):
            out[k] = e[k]
    return out


@lru_cache(maxsize=1)
def shipped() -> tuple[dict, ...]:
    entries = []
    for p in sorted(HERE.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        for e in data.get("entries", []):
            entries.append(normalise(e, "shipped"))
    ids = [e["id"] for e in entries]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        raise ValueError(f"duplicate knowledge ids: {', '.join(dup)}")
    return tuple(entries)


@lru_cache(maxsize=1)
def categories() -> dict[str, str]:
    out = {}
    for p in sorted(HERE.glob("*.json")):
        out.update(json.loads(p.read_text(encoding="utf-8")).get("categories", {}))
    return out


def _text(e: dict) -> str:
    return " ".join(str(e.get(k) or "") for k in ("topic", "concept", "explanation", "practice", "example", "correct", "mistake")) \
        + " " + " ".join(e.get("tags") or []) + " " + " ".join(s["ref"] for s in e.get("standards") or [])


def search(query: str, discipline: str | None = None, category: str | None = None, topics: list[str] | None = None,
           extra: list[dict] | None = None, include_suggestions: bool = False, levels: list[str] | None = None,
           limit: int = 6) -> list[dict]:
    """The best entries for a query, each with its score and the terms that matched."""
    pool = list(shipped()) + list(extra or [])
    if not include_suggestions:
        pool = [e for e in pool if e["level"] != "suggestion"]
    if levels:
        pool = [e for e in pool if e["level"] in levels]
    if category:
        pool = [e for e in pool if e["category"] == category.zfill(2)[:2]]
    if not pool:
        return []
    docs = [_tokens(_text(e)) for e in pool]
    avg = sum(len(d) for d in docs) / len(docs)
    df = Counter(t for d in docs for t in set(d))
    q = _tokens(query + " " + " ".join(topics or []))
    n = len(docs)
    k1, b = 1.4, 0.75
    out = []
    for e, d in zip(pool, docs):
        tf = Counter(d)
        score, hit = 0.0, []
        for t in set(q):
            if tf[t] == 0:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
            hit.append(t)
        if topics and any(tp.lower() == e["topic"].lower() or tp.lower() in [x.lower() for x in e["tags"]] for tp in topics):
            score += 3.0
            hit.append("topic")
        if discipline:
            if discipline in e["disciplines"]:
                score *= 1.5
            elif "*" not in e["disciplines"]:
                score *= 0.6
        if e["level"] in ("company", "mandatory"):
            score *= 1.3   # the owner's own rules and verified requirements come first
        if score > 0:
            out.append((score, e, hit))
    out.sort(key=lambda x: -x[0])
    res = []
    for score, e, hit in out[:max(1, limit)]:
        row = dict(e)
        row["score"] = round(score, 3)
        row["matched"] = sorted(set(hit))
        row["category_name"] = categories().get(e["category"], e["category"])
        res.append(row)
    return res


def for_topics(topics: list[str], discipline: str | None = None, extra: list[dict] | None = None, limit: int = 8) -> list[dict]:
    """Entries that explain a list of topics (one search per topic, best first, no repeats)."""
    seen, out = set(), []
    for t in topics:
        for e in search(t, discipline=discipline, topics=[t], extra=extra, limit=2):
            if e["id"] not in seen:
                seen.add(e["id"])
                out.append({"id": e["id"], "topic": e["topic"], "practice": e["practice"], "level": e["level"],
                            "validation": e["validation"], "standards": [s["ref"] for s in e["standards"]],
                            "source": e["source"].get("type") if isinstance(e["source"], dict) else e["source"]})
    return out[:limit]


def summary() -> dict[str, Any]:
    es = shipped()
    return {"entries": len(es), "categories": {k: sum(1 for e in es if e["category"] == k) for k in categories()},
            "levels": dict(Counter(e["level"] for e in es)), "validation": dict(Counter(e["validation"] for e in es))}
