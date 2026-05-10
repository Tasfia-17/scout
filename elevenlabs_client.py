"""
ElevenLabs client — TTS voice briefings + Conversational AI.
"""
import os, requests

API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
BASE_URL = "https://api.elevenlabs.io/v1"
HEADERS  = {"xi-api-key": API_KEY, "Content-Type": "application/json"}
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel — calm, professional


def tts(text: str) -> bytes:
    """Generate speech. Returns MP3 bytes."""
    if not API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    r = requests.post(
        f"{BASE_URL}/text-to-speech/{VOICE_ID}",
        headers=HEADERS,
        json={"text": text, "model_id": "eleven_turbo_v2_5",
              "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
        timeout=30,
    )
    r.raise_for_status()
    return r.content


def start_convai(system_prompt: str) -> dict:
    """
    Create an ElevenLabs Conversational AI agent and return a signed WebSocket URL.
    Returns {"signed_url": "...", "agent_id": "..."} or {"error": "..."}
    """
    if not API_KEY:
        return {"error": "ELEVENLABS_API_KEY not set"}
    try:
        r = requests.post(
            f"{BASE_URL}/convai/agents/create",
            headers=HEADERS,
            json={
                "name": "SCOUT Voice",
                "conversation_config": {
                    "agent": {
                        "prompt": {"prompt": system_prompt},
                        "first_message": "I'm SCOUT. Tell me who you want to research and I'll brief you instantly.",
                        "language": "en",
                    },
                    "tts": {"voice_id": VOICE_ID},
                },
            },
            timeout=15,
        )
        r.raise_for_status()
        agent_id = r.json().get("agent_id", "")

        ws_r = requests.get(
            f"{BASE_URL}/convai/conversation/get_signed_url",
            headers=HEADERS,
            params={"agent_id": agent_id},
            timeout=10,
        )
        ws_r.raise_for_status()
        return {"agent_id": agent_id, "signed_url": ws_r.json().get("signed_url", "")}
    except Exception as e:
        return {"error": str(e)}
