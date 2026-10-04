"""Create (or update) the Interviewer and Tutor agents and record their IDs in .env.

    python manage.py setup_agents            # create missing agents, update existing ones
"""
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from apprentice import elevenlabs as el

ENV_KEYS = {"interviewer": "INTERVIEWER_AGENT_ID", "tutor": "TUTOR_AGENT_ID"}


def _write_env(key: str, value: str) -> None:
    path = settings.BASE_DIR / ".env"
    text = path.read_text() if path.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, re.M):
        text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    path.write_text(text)


class Command(BaseCommand):
    help = "Create or update the ElevenLabs Interviewer and Tutor agents."

    def add_arguments(self, parser):
        parser.add_argument("--llm", default=settings.AGENT_LLM)
        parser.add_argument("--tts-model", default=None)

    def handle(self, *args, llm, tts_model, **opts):
        for role, key in ENV_KEYS.items():
            config = el.agent_config(role, llm, tts_model)
            existing = getattr(settings, key, "")
            if existing:
                el.update_agent(existing, config)
                self.stdout.write(self.style.SUCCESS(f"updated {role}: {existing}"))
            else:
                agent_id = el.create_agent(config)
                _write_env(key, agent_id)
                setattr(settings, key, agent_id)
                self.stdout.write(self.style.SUCCESS(f"created {role}: {agent_id}"))
