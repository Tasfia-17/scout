"""
GAP (Guarded Action Plan) pipeline — adapted from adcock-agent.
Generates, validates, and compiles structured JSON action plans.
"""
import json, re, time
from typing import Any
import llm_client


class GAPValidationError(ValueError):
    pass


GAP_SYSTEM = """You are a browser automation agent. Given a goal and the current page state (DOM + elements), 
generate a Guarded Action Plan (GAP) as strict JSON.

GAP schema:
{
  "steps": [
    {"op": "click", "target": {"hintId": "n_000001"}},
    {"op": "type", "target": {"hintId": "n_000002"}, "text": "search query", "clearFirst": true},
    {"op": "waitFor", "condition": "document.readyState === 'complete'", "timeoutMs": 3000},
    {"op": "scroll", "direction": "down", "amount": 300},
    {"op": "assert", "condition": "document.title.length > 0", "error": "page not loaded"}
  ],
  "summary": "what this plan does"
}

Allowed ops: click, type, scroll, waitFor, assert, sleep, pressKeys
Return ONLY valid JSON. No markdown."""


def generate_gap(goal: str, ism: dict, action_history: str, previous_attempt: str = "") -> dict:
    repair_block = ""
    if previous_attempt:
        repair_block = f"\nPrevious failed attempt: {previous_attempt}\nFix the plan."

    prompt = f"""Goal: {goal}
Action history: {action_history or 'none'}
Current page: {ism.get('url', '?')}
Page title: {ism.get('title', '?')}
Interactive elements (first 20):
{json.dumps(ism.get('elements', [])[:20], indent=2)}
{repair_block}

Generate a GAP to progress toward the goal."""

    resp = llm_client.chat(
        [{"role": "system", "content": GAP_SYSTEM}, {"role": "user", "content": prompt}],
        model="qwen3-8b", max_tokens=500   # fast model for browser actions
    )
    
    raw = resp.content or ""
    # Strip Qwen3 <think>...</think> chain-of-thought
    content = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if not match:
        raise GAPValidationError(f"No JSON in response: {content[:200]}")
    
    gap = json.loads(match.group())
    validate_gap(gap)
    return gap


def validate_gap(gap: dict):
    if "steps" not in gap:
        raise GAPValidationError("GAP missing 'steps'")
    allowed_ops = {"click", "type", "scroll", "waitFor", "assert", "sleep", "pressKeys"}
    for step in gap["steps"]:
        if "op" not in step:
            raise GAPValidationError(f"Step missing 'op': {step}")
        if step["op"] not in allowed_ops:
            raise GAPValidationError(f"Unknown op: {step['op']}")


def compile_gap_to_js(gap: dict) -> list[str]:
    """Compile GAP steps to executable Playwright actions."""
    actions = []
    for step in gap.get("steps", []):
        op = step["op"]
        if op == "click":
            target = step.get("target", {})
            hint = target.get("hintId", "")
            selector = target.get("selector", "")
            if hint:
                actions.append(("click_hint", hint))
            elif selector:
                actions.append(("click_selector", selector))
        elif op == "type":
            target = step.get("target", {})
            hint = target.get("hintId", "")
            text = step.get("text", "")
            clear = step.get("clearFirst", False)
            actions.append(("type", hint, text, clear))
        elif op == "scroll":
            actions.append(("scroll", step.get("direction", "down"), step.get("amount", 300)))
        elif op == "waitFor":
            actions.append(("wait", step.get("timeoutMs", 2000)))
        elif op == "sleep":
            actions.append(("sleep", step.get("ms", 500)))
        elif op == "pressKeys":
            actions.append(("press", step.get("sequence", ["Enter"])))
    return actions
