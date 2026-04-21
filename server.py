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

app = FastAPI(title="AVA — AI DeFi Co-Pilot")
app.mount("/static", StaticFiles(directory="static"), name="static")

connections: list[WebSocket] = []
last_result: dict = {}


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
    # Send last result if available
    if last_result:
        await ws.send_json({"type": "history", "data": last_result})
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "run":
                goal = data.get("goal", "").strip()
                if not goal:
                    await ws.send_json({"type": "error", "msg": "Empty goal"})
                    continue
                asyncio.create_task(_run_goal(goal))
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


@app.get("/seedance/{task_id}")
async def seedance_poll(task_id: str):
    from video_briefing import poll_seedance
    return poll_seedance(task_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
