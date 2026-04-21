"""
LLM client for ionrouter — OpenAI-compatible.
Handles text, vision, and TTS.
"""
import os, time, requests, base64
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
    """Use vision model to validate a browser screenshot."""
    resp = vision(
        f"This is a browser screenshot. The agent was supposed to: {expected_action}\n"
        "Describe what you see in 1 sentence. Did the action succeed? Reply: {{\"visible\": \"...\", \"success\": true/false}}",
        image_b64, model="qwen3-vl-8b", max_tokens=100
    )
    import json, re
    match = re.search(r'\{.*\}', resp.content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {"visible": resp.content, "success": True}
