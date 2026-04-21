"""
Screen Agent — Clicky-style visual computer use for DeFi execution.
Takes a screenshot of the browser, sends to Claude vision (Computer Use),
gets back pixel coordinates of target UI elements, clicks them.

Requires OPENROUTER_API_KEY for claude-3-5-sonnet (Computer Use).
Falls back to ionrouter qwen3-vl if key not set.
"""
import os, re, json, base64, requests
from browser import BrowserController

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
IONROUTER_KEY  = os.getenv("IONROUTER_API_KEY", "")


def detect_element_coordinates(screenshot_b64: str, element_description: str) -> dict | None:
    """
    Use Claude Computer Use (or fallback vision) to find pixel coordinates
    of a UI element in a screenshot.
    Returns: {"x": int, "y": int, "label": str} or None
    """
    if OPENROUTER_KEY:
        return _detect_via_claude_computer_use(screenshot_b64, element_description)
    return _detect_via_vision_fallback(screenshot_b64, element_description)


def _detect_via_claude_computer_use(screenshot_b64: str, element_description: str) -> dict | None:
    """Claude claude-3-5-sonnet Computer Use — most accurate pixel detection."""
    payload = {
        "model": "anthropic/claude-sonnet-4.5",
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Look at this DeFi protocol screenshot. "
                        f"Find the '{element_description}' element. "
                        f"Return ONLY JSON: {{\"x\": <pixel_x>, \"y\": <pixel_y>, \"label\": \"<what you found>\", \"found\": true/false}}"
                    )
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}
                }
            ]
        }],
        "max_tokens": 100,
    }
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=30)
        content = r.json()["choices"][0]["message"]["content"]
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"Claude Computer Use failed: {e}")
    return None


def _detect_via_vision_fallback(screenshot_b64: str, element_description: str) -> dict | None:
    """Fallback: ionrouter qwen3-vl — less accurate but works without OpenRouter."""
    payload = {
        "model": "qwen3-vl-8b",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    f"In this screenshot, find '{element_description}'. "
                    f"Estimate its center pixel coordinates. "
                    f"Reply ONLY with JSON: {{\"x\": <int>, \"y\": <int>, \"label\": \"<text>\", \"found\": true}}"
                )},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
            ]
        }],
        "max_tokens": 80,
    }
    try:
        r = requests.post(f"https://api.ionrouter.io/v1/chat/completions",
            headers={"Authorization": f"Bearer {IONROUTER_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=30)
        content = r.json()["choices"][0]["message"]["content"] or ""
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"Vision fallback failed: {e}")
    return None


async def visual_click_element(browser: BrowserController, element_description: str) -> dict:
    """
    Clicky-style: screenshot → vision → find element → click it.
    Returns result dict with coordinates and success status.
    """
    screenshot_b64 = await browser.screenshot_b64()
    coords = detect_element_coordinates(screenshot_b64, element_description)

    if not coords or not coords.get("found"):
        return {"success": False, "reason": f"Could not find '{element_description}'", "screenshot_b64": screenshot_b64}

    x, y = coords.get("x", 0), coords.get("y", 0)
    if x > 0 and y > 0:
        try:
            await browser.page.mouse.click(x, y)
            await browser.page.wait_for_timeout(1000)
            return {
                "success": True,
                "element": coords.get("label", element_description),
                "x": x, "y": y,
                "screenshot_b64": screenshot_b64,
            }
        except Exception as e:
            return {"success": False, "reason": str(e), "x": x, "y": y, "screenshot_b64": screenshot_b64}

    return {"success": False, "reason": "Invalid coordinates", "screenshot_b64": screenshot_b64}
