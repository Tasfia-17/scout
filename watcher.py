"""
Autonomous prospect watcher.
Polls prospects.csv (or /queue endpoint) and auto-triggers research runs.
Drop a prospect into prospects.csv and SCOUT researches it automatically.
"""
import asyncio, csv, os, time
from pathlib import Path

QUEUE_FILE = Path(__file__).parent / "prospects.csv"
POLL_INTERVAL = 5  # seconds


def _read_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    with open(QUEUE_FILE, newline="") as f:
        return list(csv.DictReader(f))


def _mark_done(prospect_id: str):
    rows = _read_queue()
    for r in rows:
        if r.get("id") == prospect_id:
            r["status"] = "done"
    with open(QUEUE_FILE, "w", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)


async def watch_queue(on_prospect):
    """
    Continuously polls prospects.csv for rows with status=pending.
    Calls on_prospect(goal_str) for each new prospect found.
    """
    seen = set()
    while True:
        try:
            rows = _read_queue()
            for row in rows:
                pid = row.get("id", "")
                status = row.get("status", "pending")
                goal = row.get("prospect", "").strip()
                if goal and status == "pending" and pid not in seen:
                    seen.add(pid)
                    await on_prospect(goal)
                    _mark_done(pid)
        except Exception as e:
            print(f"[watcher] error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
