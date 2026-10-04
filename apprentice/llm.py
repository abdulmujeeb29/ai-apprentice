"""Azure gpt-5.6-terra-1 over the v1 Responses API: vision events, coverage, Work Map.

Every call returns parsed JSON. Failures raise LLMError so callers can degrade
(keep previous state) instead of crashing the request.
"""
import json
import logging
import re
import time

import requests
from django.conf import settings

logger = logging.getLogger("apprentice.llm")


class LLMError(Exception):
    pass


def _extract_text(payload: dict) -> str:
    parts = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                parts.append(c.get("text", ""))
    return "".join(parts)


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if not match:
            raise LLMError(f"no JSON in model output: {text[:200]!r}")
        try:
            return json.loads(match.group(0))
        except ValueError as e:
            raise LLMError(f"bad JSON in model output: {e}") from e


def call_json(system: str, user: str, image_data_url: str | None = None,
              effort: str = "low", timeout: float = 60, retries: int = 1) -> dict:
    content = [{"type": "input_text", "text": user + "\n\nRespond with a JSON object only."}]
    if image_data_url:
        content.append({"type": "input_image", "image_url": image_data_url})
    body = {
        "model": settings.AZURE_VISION_DEPLOYMENT,
        "instructions": system,
        "input": [{"role": "user", "content": content}],
        "reasoning": {"effort": effort},
        "text": {"format": {"type": "json_object"}},
    }
    headers = {"Content-Type": "application/json", "api-key": settings.AZURE_VISION_API_KEY}
    last_err = None
    for attempt in range(retries + 1):
        t0 = time.monotonic()
        try:
            r = requests.post(settings.AZURE_VISION_ENDPOINT, json=body, headers=headers, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise LLMError(f"azure {r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:
                # Client errors will not get better on retry.
                raise LLMError(f"azure {r.status_code}: {r.text[:300]}")
            out = _parse_json(_extract_text(r.json()))
            logger.info("llm ok effort=%s %.1fs", effort, time.monotonic() - t0)
            return out
        except (requests.RequestException, LLMError) as e:
            last_err = e
            logger.warning("llm attempt %d failed: %s", attempt + 1, e)
            if isinstance(e, LLMError) and "azure 4" in str(e) and "azure 429" not in str(e):
                break
            time.sleep(0.8 * (attempt + 1))
    raise LLMError(str(last_err))
