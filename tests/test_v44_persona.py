"""v4.4 item 6: one consistent voice for MXB, the user's name, and replies that adapt to their mood."""
import random
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from engine.persona import Persona, detect_mood, parse_call_me


class TestMood(unittest.TestCase):
    def test_frustration(self):
        for text in ("it's not working", "why didn't you open chrome", "useless!!", "open notepad AGAIN",
                     "I told you to close it", "seriously, mute it"):
            self.assertEqual(detect_mood(text), "frustrated", text)

    def test_repeating_the_same_request_means_it_failed(self):
        self.assertEqual(detect_mood("Open Notepad.", ["open notepad"]), "frustrated")
        self.assertEqual(detect_mood("open notepad", ["open chrome", "close it"]), "neutral")

    def test_hurry_and_neutral(self):
        self.assertEqual(detect_mood("quickly open spotify"), "rushed")
        self.assertEqual(detect_mood("open spotify"), "neutral")
        self.assertEqual(Persona.mood_note("neutral"), "")
        self.assertIn("One short sentence", Persona.mood_note("frustrated"))
        self.assertIn("few words", Persona.mood_note("rushed"))


class TestCallMe(unittest.TestCase):
    def test_names(self):
        self.assertEqual(parse_call_me("call me S10"), "S10")
        self.assertEqual(parse_call_me("call me srinivas"), "Srinivas")
        self.assertEqual(parse_call_me("Please call me Madhu."), "Madhu")
        self.assertEqual(parse_call_me("call me Boss Man"), "Boss Man")

    def test_not_names(self):
        for text in ("call me later", "call me back in 5 minutes", "call me a cab", "call me tomorrow",
                     "please call me when you're free", "can you call me", "call mom"):
            self.assertIsNone(parse_call_me(text), text)


class TestPersona(unittest.TestCase):
    def test_prompt(self):
        p = Persona({"persona": {"user_name": "S10", "style": "crisp"}})
        text = p.prompt()
        self.assertIn("S10", text)
        self.assertIn("Brief and to the point", text)
        self.assertIn("never say 'as an AI'", text)
        self.assertEqual(Persona({"persona": {"style": "pirate"}}).style, "warm")

    def test_greeting_and_identity(self):
        p = Persona({"persona": {"user_name": "S10"}}, rng=random.Random(0))
        self.assertIn("S10", p.greeting(datetime(2026, 11, 9, 9)))
        self.assertTrue(p.greeting(datetime(2026, 11, 9, 20)).startswith(("Good evening", "Hey")))
        crisp = Persona({"persona": {"style": "crisp"}})
        self.assertEqual(crisp.greeting(datetime(2026, 11, 9, 14)), "Good afternoon. Ready.")
        self.assertIn("meeting notes", Persona({}).identity())
        self.assertEqual(p.set_user_name("Srini"), "Got it, I'll call you Srini.")
        self.assertEqual(p.user_name, "Srini")


class TestRouterUsesThePersona(unittest.TestCase):
    def router(self):
        from bench.routing import RecordingExecutor, SilentTTS
        from engine.router import IntentRouter
        ex = RecordingExecutor()
        ex.save_setting = MagicMock()
        r = IntentRouter(executor=ex, tts=SilentTTS())
        r.persona = Persona({"persona": {"user_name": "S10"}})
        return r, ex

    def test_greeting_and_call_me(self):
        r, ex = self.router()
        out = r.route("hello")
        self.assertIn("S10", out)
        out = r.route("call me Srinivas")
        self.assertIn("I'll call you Srinivas", out)
        ex.save_setting.assert_called_with("persona", "user_name", "Srinivas")
        self.assertEqual(r.persona.user_name, "Srinivas")

    def test_planner_gets_persona_and_mood(self):
        r, ex = self.router()
        r.llm = MagicMock()
        r.llm.cloud_available.return_value = False
        r.llm.plan_with_tools.return_value = {"reply": "On it.", "plan": []}
        with patch("engine.router.EnvironmentContext.get_weather_and_location", return_value=""):
            r.route("why didn't you open the downloads folder")
        system, prompt, _tool = r.llm.plan_with_tools.call_args.args
        self.assertIn("Personality: you are MXB", system)
        self.assertIn("S10", system)
        self.assertIn("sounds frustrated", prompt)


if __name__ == "__main__":
    unittest.main()
