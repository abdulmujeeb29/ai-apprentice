from django.test import SimpleTestCase

from .policy import Candidate, Moment, Weights, decide, phase_gap
from .views import scrub

NOW = 10_000.0


def moment(**kw):
    base = dict(now=NOW, activity="waiting", silence_s=5, agent_speaking=False, phase_changed=False,
                questions_asked=0, last_question_at=0)
    base.update(kw)
    return Moment(**base)


def cand(judgment=0.8, phase="env_vars", age=5, eid=1):
    return Candidate(eid, "set DEBUG=0", phase, judgment, NOW - age)


class PolicyTests(SimpleTestCase):
    def test_asks_during_build_wait(self):
        d = decide(moment(activity="waiting"), [cand()], {})
        self.assertEqual(d.action, "ask")

    def test_never_talks_over_anyone(self):
        self.assertEqual(decide(moment(agent_speaking=True), [cand()], {}).reason, "agent_speaking")
        self.assertEqual(decide(moment(silence_s=0.5), [cand()], {}).reason, "someone_talking")

    def test_never_interrupts_typing(self):
        d = decide(moment(activity="typing"), [cand()], {})
        self.assertNotEqual(d.action, "ask")

    def test_respects_gap_between_questions(self):
        d = decide(moment(last_question_at=NOW - 10), [cand()], {})
        self.assertEqual((d.action, d.reason), ("wait", "too_soon"))

    def test_budget_spent_saves_for_debrief(self):
        d = decide(moment(questions_asked=Weights().max_live_questions), [cand()], {})
        self.assertEqual(d.action, "save")

    def test_covered_phase_is_not_asked_again(self):
        full = {"env_vars": {"what": 1, "why": 1, "vs_manual": 1, "risk": 1}}
        d = decide(moment(activity="reading"), [cand()], full)
        self.assertNotEqual(d.action, "ask")

    def test_stale_topic_goes_to_debrief(self):
        d = decide(moment(activity="typing"), [cand(age=400)], {})
        self.assertEqual(d.action, "save")

    def test_phase_gap_lists_missing_items(self):
        gap, missing = phase_gap({"env_vars": {"what": 1, "why": 0.7}}, "env_vars")
        self.assertEqual(missing, ["vs_manual", "risk"])
        self.assertAlmostEqual(gap, 1 - (1 + 0.7) / 4)


class ScrubTests(SimpleTestCase):
    def test_removes_secrets_and_personal_data(self):
        text = ("mail me at sabine@firm.de, key sk_00000000fake0000example0000key000, db postgres://u:p@10.0.0.4/x, "
                "server 203.0.113.7")
        out = scrub(text)
        for leaked in ("sabine@firm.de", "sk_0000", "postgres://", "203.0.113.7"):
            self.assertNotIn(leaked, out)

    def test_keeps_plain_flags(self):
        self.assertEqual(scrub("set DEBUG=0 and port 8000"), "set DEBUG=0 and port 8000")


class CleanMessageTests(SimpleTestCase):
    def test_strips_expressive_tags_but_keeps_text(self):
        from .views import clean_message
        self.assertEqual(clean_message("[curious] No worries, what are you seeing?"), "No worries, what are you seeing?")
        self.assertEqual(clean_message("Makes sense. [thinking] A browser stack is different."),
                         "Makes sense. A browser stack is different.")

    def test_drops_app_protocol_echoes(self):
        from .views import clean_message
        for msg in ("[ASK] Natural moment", "[COACH] The new hire is now at X", "[OPEN] You can now see"):
            self.assertEqual(clean_message(msg), "")
