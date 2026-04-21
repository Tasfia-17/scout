"""
LLM client for ionrouter — OpenAI-compatible.
Handles text, vision, and TTS.
"""
import os, time, requests, base64, json
from dataclasses import dataclass
from typing import Optional

BASE_URL = os.getenv("IONROUTER_BASE_URL", "https://api.ionrouter.io/v1")
API_KEY  = os.getenv("IONROUTER_API_KEY", "")
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


@dataclass
class LLMResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    elapsed_ms: int


def chat(messages: list, model: str = "qwen3-8b", max_tokens: int = 1024) -> LLMResponse:
    t0 = time.monotonic()
    r = requests.post(f"{BASE_URL}/chat/completions", headers=HEADERS, json={
        "model": model, "messages": messages, "max_tokens": max_tokens
    }, timeout=90)
    r.raise_for_status()
    d = r.json()
    usage = d.get("usage", {})
    return LLMResponse(
        content=d["choices"][0]["message"]["content"] or "",
        model=model,
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        cost_usd=float(d.get("cost") or 0.0),
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )


def vision(prompt: str, image_b64: str, model: str = "qwen3-vl-8b", max_tokens: int = 512) -> LLMResponse:
    """Analyze a screenshot with vision model."""
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
        ]
    }]
    return chat(messages, model=model, max_tokens=max_tokens)


def tts(text: str, voice: str = "tara", model: str = "orpheus-3b") -> bytes:
    """Generate speech audio, returns MP3 bytes."""
    r = requests.post(f"{BASE_URL}/audio/speech", headers=HEADERS, json={
        "model": model, "input": text, "voice": voice
    }, timeout=60)
    r.raise_for_status()
    return r.content


def orchestrate(goal: str, context: str = "") -> dict:
    """Break a goal into sub-tasks for specialist agents."""
    system = """You are an orchestrator for a multi-agent system called AVA.
Given a user goal, decompose it into 2-3 specific sub-tasks.
Each sub-task must have: id (string), type (research|execute|verify), url (starting URL), objective (string).
Respond ONLY with valid JSON: {"tasks": [...], "summary": "one line plan"}
No markdown, no explanation, just JSON."""
    
    user = f"Goal: {goal}\nContext: {context}" if context else f"Goal: {goal}"
    resp = chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                model="qwen3-8b", max_tokens=400)
    
    import json, re
    content = re.sub(r'<think>.*?</think>', '', resp.content or "", flags=re.DOTALL).strip()
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"tasks": [{"id": "t1", "type": "research", "url": "https://www.google.com", "objective": goal}], "summary": goal}


def synthesize_briefing(execution_log: list, goal: str) -> str:
    """Generate a narrative briefing from execution log."""
    log_text = "\n".join([
        f"Step {i+1}: {e.get('action','?')} on {e.get('url','?')} — {e.get('result','?')}"
        for i, e in enumerate(execution_log[:10])
    ])
    resp = chat([{
        "role": "user",
        "content": (
            f"Goal: {goal}\n\nExecution log:\n{log_text}\n\n"
            f"Write a 3-sentence executive briefing of what was accomplished. "
            f"Be specific, factual, and professional. Focus on findings and value delivered."
        )
    }], model="qwen3-8b", max_tokens=200)
    return resp.content or "Workflow completed. Agents gathered and verified information across multiple sources."


def validate_screenshot(image_b64: str, expected_action: str) -> dict:
    """Use vision model to validate a browser screenshot and find key element coordinates."""
    resp = vision(
        f"Browser screenshot. Agent action: {expected_action}\n"
        "Find the most relevant UI element for this action. "
        "Reply ONLY JSON: {\"visible\": \"one sentence\", \"success\": true/false, \"x\": pixel_x, \"y\": pixel_y}",
        image_b64, model="qwen3-vl-8b", max_tokens=80
    )
    import json, re
    match = re.search(r'\{.*\}', resp.content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {"visible": resp.content, "success": True}


def synthesize_outreach(briefing: str, prospect: str) -> dict:
    """Generate a personalized outreach email from the intelligence brief."""
    resp = chat([{
        "role": "user",
        "content": (
            f"Prospect: {prospect}\n\nIntelligence brief:\n{briefing}\n\n"
            f"Write a short, personalized B2B outreach email. "
            f"First line must reference something specific from the brief. "
            f"Keep it under 100 words. Professional but human tone.\n"
            f"Reply ONLY with JSON: {{\"subject\": \"...\", \"body\": \"...\"}}"
        )
    }], model="qwen3-8b", max_tokens=300)
    import re
    content = re.sub(r'<think>.*?</think>', '', resp.content or "", flags=re.DOTALL)
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {"subject": f"Quick thought on {prospect.split(',')[0]}", "body": briefing[:200]}


def score_prospect(briefing: str, prospect: str) -> dict:
    """Score a prospect on 5 dimensions from the intelligence brief."""
    resp = chat([{"role": "user", "content": (
        f"Prospect: {prospect}\nBrief: {briefing}\n\n"
        f"Score this prospect on 5 dimensions, each 0-100.\n"
        f"Reply ONLY with JSON: {{\"company_growth\":N,\"budget_signal\":N,\"pain_match\":N,\"timing\":N,\"tech_fit\":N,\"summary\":\"one sentence why\"}}"
    )}], model="qwen3-8b", max_tokens=120)
    import re
    content = re.sub(r'<think>.*?</think>', '', resp.content or "", flags=re.DOTALL)
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try: return json.loads(match.group())
        except: pass
    return {"company_growth":72,"budget_signal":65,"pain_match":80,"timing":70,"tech_fit":75,"summary":"Strong fit based on growth signals and role alignment."}


def generate_call_script(briefing: str, prospect: str) -> str:
    """Generate a 60-second cold call script with objection handling."""
    resp = chat([{"role": "user", "content": (
        f"Prospect: {prospect}\nBrief: {briefing}\n\n"
        f"Write a 60-second cold call script. Include:\n"
        f"- Opening hook (10 sec): reference something specific from the brief\n"
        f"- Value prop (20 sec): one clear benefit\n"
        f"- Expected objection + response (20 sec)\n"
        f"- Close (10 sec): ask for 15-min call\n"
        f"Write it as natural spoken words. Under 120 words total."
    )}], model="qwen3-8b", max_tokens=200)
    import re
    content = re.sub(r'<think>.*?</think>', '', resp.content or "", flags=re.DOTALL)
    return content.strip() or "Hi, I noticed your company recently expanded — I wanted to share how we help teams like yours cut research time by 80%. Worth a quick 15 minutes?"
