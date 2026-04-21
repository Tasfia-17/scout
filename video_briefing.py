"""
Visual briefing generator.
Primary: flux-schnell storyboard (4-6 images) + orpheus TTS audio.
Optional: Seedance video if key is funded.
"""
import os, time, requests, base64, json
from pathlib import Path

IONROUTER_KEY = os.getenv("IONROUTER_API_KEY", "")
IONROUTER_URL = os.getenv("IONROUTER_BASE_URL", "https://api.ionrouter.io/v1")
SEEDANCE_KEY  = os.getenv("SEEDANCE_API_KEY", "")
SEEDANCE_URL  = "https://ark.ap-southeast.bytepluses.com/api/v3"
HEADERS       = {"Authorization": f"Bearer {IONROUTER_KEY}", "Content-Type": "application/json"}


def generate_briefing(
    screenshots_b64: list[str],
    narration: str,
    goal: str,
    agent_events: list[dict],
    output_dir: str = "/tmp/ava_output"
) -> dict:
    """
    Generate visual briefing: storyboard images + TTS audio.
    Falls back gracefully at each step.
    Returns dict with paths and b64 data for the dashboard.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    result = {"type": "storyboard", "narration": narration, "images": [], "audio_b64": None, "audio_path": None}

    # 1. TTS narration
    try:
        r = requests.post(f"{IONROUTER_URL}/audio/speech", headers=HEADERS,
            json={"model": "orpheus-3b", "input": narration, "voice": "tara"}, timeout=30)
        if r.status_code == 200:
            audio_path = f"{output_dir}/narration.mp3"
            with open(audio_path, "wb") as f:
                f.write(r.content)
            result["audio_path"] = audio_path
            result["audio_b64"] = base64.b64encode(r.content).decode()
    except Exception as e:
        print(f"TTS failed: {e}")

    # 2. Storyboard via flux-schnell
    storyboard_prompts = _build_storyboard_prompts(goal, agent_events, narration)
    images = []
    for i, prompt in enumerate(storyboard_prompts):
        try:
            img_b64 = _generate_image(prompt)
            if img_b64:
                path = f"{output_dir}/frame_{i}.png"
                with open(path, "wb") as f:
                    f.write(base64.b64decode(img_b64))
                images.append({"path": path, "b64": img_b64, "prompt": prompt})
        except Exception as e:
            print(f"Image {i} failed: {e}")
    result["images"] = images

    # 3. Try Seedance video (optional, non-blocking)
    if SEEDANCE_KEY and screenshots_b64:
        task = _try_seedance(screenshots_b64[0], goal)
        if task:
            result["seedance_task_id"] = task
            result["type"] = "video+storyboard"

    return result


def _build_storyboard_prompts(goal: str, events: list[dict], narration: str) -> list[str]:
    """Build 4 cinematic image prompts from the execution context."""
    goal_short = goal[:60]
    
    # Extract unique URLs visited
    urls = list(dict.fromkeys(e.get("url", "") for e in events if e.get("url")))[:3]
    url_desc = ", ".join(u.split("/")[2] for u in urls if u) or "web research"

    return [
        # Frame 1: Mission start
        f"Cinematic dark UI dashboard, holographic AI agent network activating, "
        f"glowing blue nodes connecting, mission: '{goal_short}', sci-fi aesthetic, 8k, professional photography",
        
        # Frame 2: Agents working
        f"Multiple AI browser agents simultaneously navigating websites ({url_desc}), "
        f"split-screen visualization, data streams, dark theme, neon accents, cinematic",
        
        # Frame 3: Data extraction
        f"AI agent extracting structured data from web pages, glowing text highlights, "
        f"knowledge graph forming in real-time, dark background, blue and purple tones",
        
        # Frame 4: Mission complete
        f"Mission accomplished dashboard showing research results, "
        f"clean data visualization, green success indicators, professional dark UI, cinematic wide shot",
    ]


def _generate_image(prompt: str) -> str | None:
    """Generate one image via flux-schnell, return b64 string."""
    r = requests.post(f"{IONROUTER_URL}/images/generations", headers=HEADERS,
        json={"model": "flux-schnell", "prompt": prompt, "n": 1,
              "size": "1280x720", "response_format": "b64_json"},
        timeout=30)
    if r.status_code == 200:
        data = r.json()
        return data["data"][0].get("b64_json")
    return None


def _try_seedance(first_frame_b64: str, goal: str) -> str | None:
    """Try Seedance video generation. Returns task_id or None."""
    try:
        r = requests.post(f"{SEEDANCE_URL}/contents/generations/tasks",
            headers={"Authorization": f"Bearer {SEEDANCE_KEY}", "Content-Type": "application/json"},
            json={
                "model": "dreamina-seedance-2-0-fast-260128",
                "content": [
                    {"type": "text", "text": f"Cinematic AI agent dashboard visualization. {goal[:80]}. "
                     "Dark theme, glowing data streams, professional. [Image 1] as first frame."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{first_frame_b64}"}, "role": "first_frame"}
                ],
                "ratio": "16:9", "duration": 8, "generate_audio": False, "watermark": False,
            }, timeout=20)
        data = r.json()
        if "error" not in data:
            return data.get("id")
        print(f"Seedance: {data['error']['code']}")
    except Exception as e:
        print(f"Seedance failed: {e}")
    return None


def poll_seedance(task_id: str) -> dict:
    """Poll Seedance task status."""
    try:
        r = requests.get(f"{SEEDANCE_URL}/contents/generations/tasks/{task_id}",
            headers={"Authorization": f"Bearer {SEEDANCE_KEY}"}, timeout=15)
        data = r.json()
        status = data.get("status", "unknown")
        if status == "succeeded":
            return {"status": "done", "video_url": data.get("content", {}).get("video_url")}
        return {"status": status}
    except Exception as e:
        return {"status": "error", "error": str(e)}
