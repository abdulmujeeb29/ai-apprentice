"""ElevenAgents: create/update the Interviewer and Tutor, and mint signed URLs."""
import requests
from django.conf import settings

from . import prompts

API = "https://api.elevenlabs.io/v1"

VOICES = {
    "interviewer": "bIHbv24MWmeRgasZH58o",  # Will - relaxed, curious
    "tutor": "Xb7hH8MSUJpSbSDYk0k2",        # Alice - clear, engaging educator
}

SKIP_TURN = {
    "type": "system",
    "name": "skip_turn",
    "description": "Stay silent this turn ONLY when the person is clearly talking to someone else or muttering to themselves. Never use it when they address you or ask anything.",
    "params": {"system_tool_type": "skip_turn"},
}


ASR_KEYWORDS = ["Thales Ops", "ThalesOps", "Nixpacks", "Dockerfile", "Caddy", "nginx", "certbot", "CSRF",
                "DEBUG", "env vars", "gunicorn", "Django", "pay with thales", "rollback", "subdomain", "migrations"]


class ElevenLabsError(Exception):
    pass


def _headers():
    return {"xi-api-key": settings.ELEVENLABS_API_KEY, "Content-Type": "application/json"}


def agent_config(role: str, llm: str, tts_model: str | None = None) -> dict:
    if role == "interviewer":
        name, prompt, first, placeholders = (
            "Sidecar - Interviewer", prompts.INTERVIEWER_PROMPT, prompts.INTERVIEWER_FIRST_MESSAGE, {})
        eagerness, temperature = "patient", 0.5
    else:
        name, prompt, first = "Sidecar - Tutor", prompts.TUTOR_PROMPT, prompts.TUTOR_FIRST_MESSAGE
        placeholders = {"work_map": "(no work map loaded)", "check_scenario": "(none)"}
        eagerness, temperature = "normal", 0.4
    tts = {"voice_id": VOICES[role], "stability": 0.5, "similarity_boost": 0.8, "speed": 1.0}
    if tts_model:
        tts["model_id"] = tts_model
    return {
        "name": name,
        "tags": ["hack-nation", "sidecar"],
        "conversation_config": {
            "agent": {
                "first_message": first,
                "language": "en",
                "dynamic_variables": {"dynamic_variable_placeholders": placeholders},
                "prompt": {
                    "prompt": prompt,
                    "llm": llm,
                    "temperature": temperature,
                    # The tutor must always answer a stuck new hire, so it gets no skip_turn.
                    "built_in_tools": {"skip_turn": SKIP_TURN if role == "interviewer" else None},
                },
            },
            "tts": tts,
            # -1: never nudge the person after silence. Long silences are normal while they work.
            "turn": {"turn_timeout": -1, "turn_eagerness": eagerness},
            "asr": {"keywords": ASR_KEYWORDS},
        },
    }


def create_agent(config: dict) -> str:
    r = requests.post(f"{API}/convai/agents/create", json=config, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        raise ElevenLabsError(f"create failed {r.status_code}: {r.text[:600]}")
    return r.json()["agent_id"]


def update_agent(agent_id: str, config: dict) -> None:
    r = requests.patch(f"{API}/convai/agents/{agent_id}", json=config, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        raise ElevenLabsError(f"update failed {r.status_code}: {r.text[:600]}")


def get_agent(agent_id: str) -> dict:
    r = requests.get(f"{API}/convai/agents/{agent_id}", headers=_headers(), timeout=30)
    if r.status_code >= 400:
        raise ElevenLabsError(f"get failed {r.status_code}: {r.text[:300]}")
    return r.json()


def signed_url(agent_id: str) -> str:
    r = requests.get(f"{API}/convai/conversation/get-signed-url", params={"agent_id": agent_id},
                     headers=_headers(), timeout=15)
    if r.status_code >= 400:
        raise ElevenLabsError(f"signed url failed {r.status_code}: {r.text[:300]}")
    return r.json()["signed_url"]
