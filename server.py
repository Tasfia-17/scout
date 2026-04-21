"""
FastAPI server — WebSocket-based real-time dashboard for AVA.
"""
import asyncio, json, os, base64
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from orchestrator import AVAOrchestrator

app = FastAPI(title="SCOUT — AI Sales Intelligence")
app.mount("/static", StaticFiles(directory="static"), name="static")

connections: list[WebSocket] = []
last_result: dict = {}
autonomous_task = None  # background watcher task


async def broadcast(msg: dict):
    dead = []
    for ws in connections:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connections.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connections.append(ws)
    if last_result:
        await ws.send_json({"type": "history", "data": last_result})
    # Send autonomous mode status
    await ws.send_json({"type": "auto_status", "active": autonomous_task is not None and not autonomous_task.done()})
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "run":
                goal = data.get("goal", "").strip()
                if not goal:
                    await ws.send_json({"type": "error", "msg": "Empty goal"})
                    continue
                asyncio.create_task(_run_goal(goal))
            elif data.get("type") == "auto_start":
                await _start_autonomous()
            elif data.get("type") == "auto_stop":
                await _stop_autonomous()
            elif data.get("type") == "queue_add":
                await _add_to_queue(data.get("prospect", ""))
    except WebSocketDisconnect:
        connections.remove(ws)


async def _run_goal(goal: str):
    global last_result

    async def on_update(msg):
        await broadcast(msg)
        if isinstance(msg, dict) and msg.get("type") == "briefing":
            b = msg.get("briefing", {})
            # Stream storyboard frames
            for i, img in enumerate(b.get("images", [])):
                await broadcast({"type": "storyboard_frame", "index": i, "b64": img["b64"], "prompt": img.get("prompt","")})
            # Stream audio
            if b.get("audio_b64"):
                await broadcast({"type": "audio", "b64": b["audio_b64"]})

    def sync_update(msg):
        asyncio.create_task(on_update(msg))

    orch = AVAOrchestrator(headless=True, on_update=sync_update)
    result = await orch.run(goal)
    last_result = result

    # Send screenshots
    for i, b64 in enumerate(orch.all_screenshots[:6]):
        await broadcast({"type": "screenshot", "index": i, "b64": b64})


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _start_autonomous():
    global autonomous_task
    from watcher import watch_queue
    if autonomous_task and not autonomous_task.done():
        return
    await broadcast({"type": "auto_status", "active": True})
    await broadcast({"type": "status", "msg": "Autonomous mode active — watching prospects.csv"})

    async def on_prospect(goal: str):
        await broadcast({"type": "status", "msg": f"[AUTO] New prospect: {goal}"})
        await _run_goal(goal)

    autonomous_task = asyncio.create_task(watch_queue(on_prospect))


async def _stop_autonomous():
    global autonomous_task
    if autonomous_task:
        autonomous_task.cancel()
        autonomous_task = None
    await broadcast({"type": "auto_status", "active": False})
    await broadcast({"type": "status", "msg": "Autonomous mode stopped"})


async def _add_to_queue(prospect: str):
    """Add a prospect to the CSV queue from the dashboard."""
    if not prospect.strip():
        return
    import csv
    from pathlib import Path
    queue_file = Path("prospects.csv")
    rows = []
    if queue_file.exists():
        with open(queue_file, newline="") as f:
            rows = list(csv.DictReader(f))
    new_id = str(max((int(r.get("id",0)) for r in rows), default=0) + 1)
    rows.append({"id": new_id, "prospect": prospect, "status": "pending"})
    with open(queue_file, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id","prospect","status"])
        w.writeheader()
        w.writerows(rows)
    await broadcast({"type": "status", "msg": f"Added to queue: {prospect}"})


@app.post("/demo")
async def demo_mode():
    """Fire pre-cached demo events so the demo never breaks live."""
    import asyncio
    asyncio.create_task(_run_demo())
    return {"status": "started"}


async def _run_demo():
    import asyncio
    events = [
        {"type": "status", "msg": "Goal: Marcus Rivera, CTO at Linear (linear.app)"},
        {"type": "plan", "summary": "Research Linear's product, team, and competitive position", "tasks": [
            {"id": "t1", "type": "research", "url": "https://linear.app", "objective": "Research Linear's product, pricing, and recent launches"},
            {"id": "t2", "type": "research", "url": "https://www.google.com", "objective": "Find recent news and funding about Linear"},
            {"id": "t3", "type": "verify",   "url": "https://www.google.com", "objective": "Research competitors: Jira, Asana, Notion and how Linear positions against them"},
        ]},
        {"type": "status", "msg": "Launching 3 agents with ERC-8004 identities..."},
        {"type": "agent_event", "agent_id": "agent_t1", "cycle": 0, "url": "https://linear.app", "action": "Navigating to Linear homepage", "vision": {}, "signature": {"signer": "0x7FF67D3cF058B79dC68dDf6B586D4D046dbD6eAF", "verified": True}, "payment": {"nonce": "0xabc123..."}},
        {"type": "agent_event", "agent_id": "agent_t2", "cycle": 0, "url": "https://www.google.com", "action": "Searching: Linear app funding news 2025", "vision": {}, "signature": {"signer": "0x7FF67D3cF058B79dC68dDf6B586D4D046dbD6eAF", "verified": True}, "payment": {"nonce": "0xdef456..."}},
        {"type": "agent_event", "agent_id": "agent_t3", "cycle": 0, "url": "https://www.google.com", "action": "Searching: Linear vs Jira vs Asana comparison", "vision": {}, "signature": {"signer": "0x7FF67D3cF058B79dC68dDf6B586D4D046dbD6eAF", "verified": True}, "payment": {"nonce": "0xghi789..."}},
        {"type": "agent_event", "agent_id": "agent_t1", "cycle": 1, "url": "https://linear.app", "action": "Extracted: Linear is a project management tool built for speed", "vision": {"success": True}, "signature": {"signer": "0x7FF67D3cF058B79dC68dDf6B586D4D046dbD6eAF", "verified": True}, "payment": {"nonce": "0xjkl012..."}},
        {"type": "identities", "identities": [
            {"address": "0x7FF67D3cF058B79dC68dDf6B586D4D046dbD6eAF", "nft_id": 4821, "registration": {"status": "simulated", "chain": "taiko", "chain_id": 167000}},
            {"address": "0x7FF67D3cF058B79dC68dDf6B586D4D046dbD6eAF", "nft_id": 4822, "registration": {"status": "simulated", "chain": "taiko", "chain_id": 167000}},
            {"address": "0x7FF67D3cF058B79dC68dDf6B586D4D046dbD6eAF", "nft_id": 4823, "registration": {"status": "simulated", "chain": "taiko", "chain_id": 167000}},
        ]},
        {"type": "a2a_messages", "messages": [
            {"sender": "agent_t1", "recipient": "broadcast", "type": "finding", "content": {"url": "linear.app", "snippet": "Linear raised $35M Series B. Built for high-performance engineering teams."}, "ts": 0},
            {"sender": "agent_t2", "recipient": "broadcast", "type": "finding", "content": {"url": "google.com", "snippet": "Linear valued at $400M. Competing directly with Jira for developer-first teams."}, "ts": 0},
            {"sender": "agent_t3", "recipient": "agent_t1",  "type": "finding", "content": {"url": "google.com", "snippet": "Linear's key differentiator: speed and keyboard-first UX vs Jira's complexity."}, "ts": 0},
        ]},
        {"type": "payments", "payments": [
            {"wallet": "0x7FF67D3cF058B79dC68dDf6B586D4D046dbD6eAF", "total_payments": 6, "total_usdc": 0.000006, "network": "Base Sepolia (eip155:84532)"},
        ]},
        {"type": "narration", "text": "Linear is a project management platform built for high-performance engineering teams, having raised $35M in Series B funding at a $400M valuation. Marcus Rivera, as CTO, is likely focused on developer tooling, engineering velocity, and reducing operational overhead. Linear's key competitive advantage over Jira is its speed and keyboard-first UX, which resonates strongly with modern engineering organizations prioritizing developer experience."},
        {"type": "outreach", "subject": "How we help CTOs like you cut research overhead by 80%", "body": "Hi Marcus,\n\nI noticed Linear recently raised its Series B and is scaling fast — engineering velocity is clearly a priority.\n\nWe built SCOUT to give sales teams the same speed advantage Linear gives engineering teams. A prospect walks in, agents research them in 90 seconds, and your rep walks into the call already knowing what matters.\n\nWorth a 15-minute call this week?\n\nBest,\nScout"},
        {"type": "score", "score": {"company_growth": 88, "budget_signal": 72, "pain_match": 85, "timing": 78, "tech_fit": 90, "summary": "High-growth Series B company with clear engineering velocity focus — strong fit for productivity tooling."}},
        {"type": "call_script", "text": "Hi Marcus, I saw Linear just closed its Series B — congrats on the growth.\n\nI'm calling because we built something that gives sales teams the same speed advantage Linear gives engineering teams. Our agents research any prospect in 90 seconds and deliver a spoken briefing before the call.\n\nI know you're probably thinking — another sales tool. But this one actually replaces Clay and a research assistant entirely.\n\nWould 15 minutes this week make sense to show you a live run?"},
        {"type": "complete", "elapsed_sec": 42},
    ]
    for event in events:
        await broadcast(event)
        await asyncio.sleep(1.2)


@app.get("/seedance/{task_id}")
async def seedance_poll(task_id: str):
    from video_briefing import poll_seedance
    return poll_seedance(task_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
