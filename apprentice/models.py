import uuid

from django.db import models


class WorkMap(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    data = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Session(models.Model):
    CAPTURE = "capture"
    TEACH = "teach"
    KINDS = [(CAPTURE, "Capture"), (TEACH, "Teach")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=KINDS, default=CAPTURE)
    title = models.CharField(max_length=200, default="Deploy an app on Thales Ops")
    created = models.DateTimeField(auto_now_add=True)
    # Latest read of the screen, fed back to the vision model so it reports changes only.
    screen = models.TextField(blank=True, default="")
    phase = models.CharField(max_length=40, blank=True, default="")
    activity = models.CharField(max_length=12, blank=True, default="idle")
    # Per-phase checklist scores written by the background assessor:
    # {"env_vars": {"what": 1.0, "why": 0.5, "vs_manual": 0.0, "risk": 0.0}, ...}
    coverage = models.JSONField(default=dict)
    questions_asked = models.IntegerField(default=0)
    last_question_at = models.FloatField(default=0)  # unix seconds
    debrief = models.JSONField(default=dict)
    # Teach sessions only.
    work_map = models.ForeignKey(WorkMap, null=True, blank=True, on_delete=models.SET_NULL, related_name="teach_sessions")
    coached_phases = models.JSONField(default=list)
    result = models.JSONField(default=dict)
    # Capture sessions: the map they produced.
    produced_map = models.OneToOneField(WorkMap, null=True, blank=True, on_delete=models.SET_NULL, related_name="source_session")

    class Meta:
        ordering = ["-created"]


class Keyframe(models.Model):
    """A small, redacted screenshot of a moment that mattered. Stored in the database so it
    survives redeploys without a file store."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="keyframes")
    at = models.FloatField()
    image = models.BinaryField()  # JPEG

    class Meta:
        ordering = ["at", "id"]


class Event(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="events")
    keyframe = models.ForeignKey(Keyframe, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    at = models.FloatField()  # unix seconds
    phase = models.CharField(max_length=40, blank=True, default="")
    text = models.TextField()
    judgment = models.FloatField(default=0)  # 0..1, how much expert judgment the action carried
    asked = models.BooleanField(default=False)

    class Meta:
        ordering = ["at", "id"]


class Utterance(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="utterances")
    at = models.FloatField()
    role = models.CharField(max_length=10)  # "user" | "agent"
    text = models.TextField()

    class Meta:
        ordering = ["at", "id"]


class Decision(models.Model):
    """Every ask/wait/save decision with its inputs, so thresholds are tuned from data."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="decisions")
    at = models.FloatField()
    action = models.CharField(max_length=10)
    reason = models.CharField(max_length=40)
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["at", "id"]
