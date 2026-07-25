"""Adversaria MCP server — sovereign-first, read-only access to your local meeting
notes and to-dos.

Runs locally over stdio and reads the same on-device SQLite database the desktop
app writes (``meetings.db``). It is **read-only** (the DB is opened in ``mode=ro``)
and makes **no network calls** — your data only ever leaves your machine if *you*
point an MCP client at a cloud model. Connect it to whatever you like: Claude
Desktop, Claude Code, an OpenAI-compatible client, or a local LLM.

Configure the DB location with the ``ADVERSARIA_DB`` environment variable;
otherwise the per-OS default app-data path is used.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Adversaria")

# --- Database access (read-only) ---------------------------------------------


def _db_path() -> Path:
    """Resolve the meetings.db path: ADVERSARIA_DB override, else the per-OS
    app-data location used by the desktop app."""
    override = os.environ.get("ADVERSARIA_DB")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/meeting-note-taker/meetings.db"
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home())
        return base / "meeting-note-taker" / "meetings.db"
    return Path.home() / ".local/share/meeting-note-taker/meetings.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Adversaria database not found at {path}. "
            "Open the app at least once, or set ADVERSARIA_DB to its meetings.db."
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# --- 'Me'/'Them' cleanup (mirrors the app: they're generic capture labels) ----

_SPEAKER_LABELS = {"me", "them"}


def _clean_attendees(raw: str | None) -> list[str]:
    try:
        names = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        names = []
    return [
        n for n in names
        if isinstance(n, str) and n.strip().lower() not in _SPEAKER_LABELS
    ]


def _clean_title(title: str) -> str:
    if not title:
        return title
    t = re.sub(r"\s*\b(and|with|&|,)\s+(me|them)\b", "", title, flags=re.IGNORECASE)
    t = re.sub(r"\b(me|them)\b\s*(and|with|&|,)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(me|them)\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s{2,}", " ", t).strip().strip(",&").strip()
    t = re.sub(r"\s+(and|with|&)$", "", t, flags=re.IGNORECASE).strip()
    return t or title


def _tag_labels(raw: str | None) -> list[str]:
    try:
        tags = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []
    out: list[str] = []
    for t in tags:
        if isinstance(t, dict) and isinstance(t.get("label"), str):
            out.append(t["label"])
        elif isinstance(t, str):
            out.append(t)
    return out


def _strip_speaker_prefixes(transcript: str) -> str:
    """Drop the leading 'Me: ' / 'Them: ' labels from each transcript line."""
    if not transcript:
        return transcript
    lines = [
        re.sub(r"^\s*(me|them)\s*:\s*", "", line, flags=re.IGNORECASE)
        for line in transcript.splitlines()
    ]
    return "\n".join(lines)


def _snippet(summary: str | None, limit: int = 220) -> str:
    if not summary:
        return ""
    # Strip markdown emphasis/headings for a clean preview.
    text = re.sub(r"[*#`>_-]", " ", summary)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _to_local_iso(recorded_at: str | None) -> str:
    """Convert a stored UTC timestamp to this machine's local timezone.

    The desktop app stores ``recorded_at`` as a UTC ISO 8601 string (e.g.
    ``2026-06-22T14:02:47+00:00``). Returning it in local time means clients
    that echo the wall-clock show the correct hour instead of UTC. Falls back
    to the raw value if it can't be parsed; assumes UTC if no offset is present."""
    if not recorded_at:
        return recorded_at or ""
    try:
        dt = datetime.fromisoformat(recorded_at)
    except ValueError:
        return recorded_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().isoformat()


def _meeting_summary_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": _clean_title(row["title"]),
        "date": _to_local_iso(row["recorded_at"]),
        "duration_minutes": round((row["duration_seconds"] or 0) / 60),
        "attendees": _clean_attendees(row["attendees"]),
        "tags": _tag_labels(row["tags"]),
        "snippet": _snippet(row["summary"]),
    }


# --- Tools -------------------------------------------------------------------


@mcp.tool()
def list_recent_meetings(limit: int = 20) -> list[dict[str, Any]]:
    """List your most recent meetings, newest first.

    Each entry has: id, title, date, duration_minutes, attendees, tags, and a
    short summary snippet. Use `get_meeting` for the full notes of one.
    """
    limit = max(1, min(int(limit), 200))
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, title, recorded_at, duration_seconds, attendees, tags, summary "
            "FROM meetings ORDER BY recorded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_meeting_summary_row(r) for r in rows]


@mcp.tool()
def search_meetings(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search your meetings by title, summary, or transcript content.

    Returns matching meetings (id, title, date, attendees, tags, snippet),
    newest first. Use `get_meeting` to read a full match.
    """
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit), 200))
    like = f"%{q}%"
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, title, recorded_at, duration_seconds, attendees, tags, summary "
            "FROM meetings "
            "WHERE title LIKE ? OR summary LIKE ? OR transcript LIKE ? "
            "ORDER BY recorded_at DESC LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
    return [_meeting_summary_row(r) for r in rows]


@mcp.tool()
def get_meeting(meeting_id: int) -> dict[str, Any]:
    """Get the full notes for one meeting: title, date, duration, attendees,
    tags, the generated summary (markdown), your personal notes, and the
    transcript (plain, without speaker labels)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, title, recorded_at, duration_seconds, attendees, tags, "
            "summary, user_notes, transcript, template_used "
            "FROM meetings WHERE id = ?",
            (int(meeting_id),),
        ).fetchone()
    if row is None:
        raise ValueError(f"No meeting with id {meeting_id}.")
    return {
        "id": row["id"],
        "title": _clean_title(row["title"]),
        "date": _to_local_iso(row["recorded_at"]),
        "duration_minutes": round((row["duration_seconds"] or 0) / 60),
        "attendees": _clean_attendees(row["attendees"]),
        "tags": _tag_labels(row["tags"]),
        "template": row["template_used"],
        "summary": row["summary"] or "",
        "personal_notes": row["user_notes"] or "",
        "transcript": _strip_speaker_prefixes(row["transcript"] or ""),
    }


@mcp.tool()
def get_action_items(status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
    """Get your to-dos (action items) across all meetings.

    status: 'open' (not done, default), 'done', 'overdue' (past due & not done),
    'today' (due today & not done), or 'all'. Each item has: id, text, assignee,
    due (yyyy-mm-dd or ''), done, meeting_id, meeting_title, meeting_date.
    """
    status = (status or "open").strip().lower()
    limit = max(1, min(int(limit), 500))
    today = date.today().isoformat()

    where = "1=1"
    params: list[Any] = []
    if status == "open":
        where = "a.done = 0"
    elif status == "done":
        where = "a.done = 1"
    elif status == "overdue":
        where = "a.done = 0 AND a.due != '' AND a.due < ?"
        params.append(today)
    elif status == "today":
        where = "a.done = 0 AND a.due = ?"
        params.append(today)
    elif status != "all":
        raise ValueError(
            "status must be one of: open, done, overdue, today, all."
        )

    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT a.id, a.text, a.assignee, a.due, a.done, "
            f"a.meeting_id, m.title AS m_title, m.recorded_at AS m_date "
            f"FROM action_items a JOIN meetings m ON m.id = a.meeting_id "
            f"WHERE {where} "
            f"ORDER BY (a.due = '') ASC, a.due ASC, m.recorded_at DESC "
            f"LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "text": r["text"],
            "assignee": r["assignee"] or "",
            "due": r["due"] or "",
            "done": bool(r["done"]),
            "meeting_id": r["meeting_id"],
            "meeting_title": _clean_title(r["m_title"]),
            "meeting_date": _to_local_iso(r["m_date"]),
        }
        for r in rows
    ]


def main() -> None:
    """Console entry point — run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
