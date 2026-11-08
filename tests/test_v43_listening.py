"""
v4.3.1 listening and tool-use fixes, from a real run on a laptop:
- the Silero VAD was called statelessly per 32 ms frame (9% of quiet speech detected)
- quiet microphone (speech at RMS ~0.004) and a fixed energy threshold that fires on noise
- Whisper's prompt repeated back on noise ("open app, open app, ...")
- "Ahh, MXB" and "open chrome, MXB" missed the wake word
- "open notebook" opened nothing
- llama3.2:1b timed out three times on a ~4,700-token prompt (136 s, then failure)
"""
import importlib.util
import json
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import requests

import tests._stubs  # noqa: F401
from engine.actions_catalog import (CORE_ACTIONS, action_names, plan_tool_schema, planner_system_prompt,
                                    relevant_actions)
from engine.listening import (InputAGC, StreamingVAD, clean_transcript, db_to_gain, energy_speech_prob, gain_to_db,
                              is_speech, whisper_options)
from engine.llm_client import LLMClient, LocalModelPaused, estimate_tokens
from engine.wake_word import WakeWordGate
from utils.app_launcher import SmartAppLauncher, parse_start_apps

FRAME = 512
DATA = Path(__file__).parent / "data"


def rms(x) -> float:
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(x * x)))


def noise_frame(rng, level):
    return rng.normal(0, level, FRAME).astype(np.float32)


def tone_frame(level, freq=220.0, phase=0.0):
    t = (np.arange(FRAME) + phase) / 16000.0
    return (np.sin(2 * np.pi * freq * t) * level * np.sqrt(2)).astype(np.float32)


def run_room(agc, seconds_noise=2.0, seconds_talk=6.0, noise=0.0007, speech=0.004, rng=None):
    """Quiet room, then speech bursts (0.5 s on, 0.3 s off) over the same noise. Returns output frames."""
    rng = rng or np.random.default_rng(7)
    out = []
    for _ in range(int(seconds_noise / 0.032)):
        out.append(agc.process(noise_frame(rng, noise)))
    for i in range(int(seconds_talk / 0.032)):
        talking = (i % 25) < 16
        frame = noise_frame(rng, noise) + (tone_frame(speech, phase=i * FRAME) if talking else 0)
        out.append((talking, agc.process(frame)))
    return out


class TestInputGain(unittest.TestCase):
    def test_db_helpers(self):
        self.assertAlmostEqual(db_to_gain(20), 10.0, places=5)
        self.assertAlmostEqual(gain_to_db(10.0), 20.0, places=5)

    def test_quiet_speech_is_amplified_toward_the_target(self):
        agc = InputAGC()
        frames = run_room(agc)
        talk = [f for item in frames if isinstance(item, tuple) for t, f in [item] if t]
        last = talk[-40:]
        self.assertGreater(agc.gain_db, 15.0)                      # about +20 dB for -48 dBFS speech
        self.assertLessEqual(agc.gain_db, 30.0 + 1e-6)             # never past the cap
        self.assertGreater(np.median([rms(f) for f in last]), 0.04)

    def test_loud_speech_is_left_alone_and_never_clips(self):
        agc = InputAGC()
        frames = run_room(agc, noise=0.002, speech=0.3)
        self.assertLess(agc.gain_db, 1.0)
        peak = max(float(np.max(np.abs(f if not isinstance(f, tuple) else f[1]))) for f in frames)
        self.assertLess(peak, 1.0)

    def test_room_noise_is_not_amplified_past_the_ceiling(self):
        agc = InputAGC()
        rng = np.random.default_rng(3)
        for _ in range(300):                                        # ~10 s of fan noise, nobody talking
            agc.process(noise_frame(rng, 0.002))
        self.assertLessEqual(agc.noise_after_gain, agc.noise_ceiling + 1e-6)
        self.assertGreaterEqual(agc.gain, 1.0)

    def test_sudden_shout_turns_the_gain_down_fast(self):
        agc = InputAGC()
        run_room(agc)
        high = agc.gain
        out = agc.process(tone_frame(0.4, phase=0))
        self.assertLess(agc.gain, high * 0.5)                      # first loud frame cuts the gain
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)      # never past full scale
        self.assertLess(rms(out), 0.5)

    def test_frames_while_mxb_talks_do_not_train_the_gain(self):
        agc = InputAGC()
        run_room(agc)
        before = (agc.gain, agc.noise, agc.speech, len(agc.history))
        for i in range(50):
            agc.process(tone_frame(0.2, phase=i * FRAME), adapt=False)
        self.assertEqual((agc.gain, agc.noise, agc.speech, len(agc.history)), before)

    def test_off_mode_passes_audio_through_but_still_tracks_noise(self):
        agc = InputAGC(mode="off")
        rng = np.random.default_rng(1)
        frame = noise_frame(rng, 0.001)
        for _ in range(50):
            out = agc.process(frame)
        np.testing.assert_array_equal(out, frame)
        self.assertEqual(agc.gain, 1.0)
        self.assertAlmostEqual(agc.noise_after_gain, rms(frame), places=4)

    def test_config_modes(self):
        self.assertEqual(InputAGC.from_config({}).mode, "auto")
        fixed = InputAGC.from_config({"engine": {"input_gain": "12 dB"}})
        self.assertEqual(fixed.mode, "fixed")
        self.assertAlmostEqual(fixed.gain_db, 12.0, places=4)
        self.assertEqual(InputAGC.from_config({"engine": {"input_gain": "off"}}).mode, "off")
        self.assertEqual(InputAGC.from_config({"engine": {"input_gain": "loud"}}).mode, "auto")   # typo -> auto
        capped = InputAGC.from_config({"engine": {"max_input_gain_db": 12}})
        self.assertAlmostEqual(gain_to_db(capped.max_gain), 12.0, places=4)

    def test_digital_silence_and_empty_frames(self):
        agc = InputAGC()
        for _ in range(100):
            out = agc.process(np.zeros(FRAME, dtype=np.float32))
        self.assertTrue(np.all(out == 0) and np.all(np.isfinite(out)))
        self.assertEqual(len(agc.process(np.zeros(0, dtype=np.float32))), 0)


class TestSpeechDecision(unittest.TestCase):
    def test_relative_to_the_noise_floor(self):
        self.assertTrue(is_speech(0.9, 0.001, 0.001))               # VAD sure
        self.assertFalse(is_speech(0.05, 0.0012, 0.001))            # noise-level frame, VAD unsure
        self.assertTrue(is_speech(0.2, 0.004, 0.001))               # VAD unsure but 4x the floor
        self.assertTrue(is_speech(0.0, 0.008, 0.001))               # clearly loud
        self.assertFalse(is_speech(0.0, 0.002, 0.001))
        # A noisy room: the same 0.004 frame that is speech in a quiet room is just the fan here.
        self.assertFalse(is_speech(0.1, 0.004, 0.003))

    def test_energy_fallback_when_the_vad_cannot_load(self):
        self.assertEqual(energy_speech_prob(0.05, 0.005), 1.0)
        self.assertEqual(energy_speech_prob(0.01, 0.005), 0.0)
        self.assertEqual(energy_speech_prob(0.0015, 0.0001), 0.0)   # absolute floor


class FakeSession:
    """Mimics faster-whisper >= 1.1's ONNX session: returns state + 1 so carried state is visible."""
    def __init__(self):
        self.calls = []

    def get_inputs(self):
        return [MagicMock(name=n) for n in ("input", "h", "c")]

    def run(self, _outputs, feeds):
        self.calls.append({k: np.array(v, copy=True) for k, v in feeds.items()})
        return np.array([[0.25 + 0.01 * len(self.calls)]], dtype=np.float32), feeds["h"] + 1, feeds["c"] + 1


class TestStreamingVAD(unittest.TestCase):
    def _model(self):
        session = FakeSession()
        for inp, n in zip(session.get_inputs(), ("input", "h", "c")):
            inp.name = n
        model = MagicMock(session=session)
        model.session.get_inputs = lambda: [type("I", (), {"name": n})() for n in ("input", "h", "c")]
        return model, session

    def test_keeps_state_and_context_between_frames(self):
        model, session = self._model()
        vad = StreamingVAD(model)
        self.assertEqual(vad.kind, "session")
        a = np.full(FRAME, 0.1, dtype=np.float32)
        b = np.full(FRAME, 0.2, dtype=np.float32)
        self.assertAlmostEqual(vad(a), 0.26, places=5)
        vad(b)
        first, second = session.calls
        self.assertEqual(first["input"].shape, (1, FRAME + 64))
        self.assertTrue(np.all(first["input"][0, :64] == 0))                # no context yet
        self.assertTrue(np.allclose(second["input"][0, :64], 0.1))          # previous frame's tail
        self.assertTrue(np.all(first["h"] == 0) and np.all(second["h"] == 1))   # memory carried
        vad.reset()
        vad(a)
        self.assertTrue(np.all(session.calls[-1]["h"] == 0))

    def test_old_faster_whisper_api(self):
        class OldModel:                       # faster-whisper 0.10-1.0: model(x, state, sr) -> (out, state)
            def __init__(self):
                self.states = []

            def get_initial_state(self, batch_size):
                return 0

            def __call__(self, x, state, sr):
                self.states.append(state)
                return np.array([[0.7]]), state + 1
        model = OldModel()
        vad = StreamingVAD(model)
        self.assertEqual(vad.kind, "state")
        for _ in range(3):
            self.assertAlmostEqual(vad(np.zeros(FRAME)), 0.7, places=5)
        self.assertEqual(model.states, [0, 1, 2])

    def test_unknown_model_falls_back_to_plain_calls(self):
        vad = StreamingVAD(lambda x: [0.4])
        self.assertEqual(vad.kind, "stateless")
        self.assertAlmostEqual(vad(np.zeros(FRAME)), 0.4, places=5)

    def test_broken_session_degrades_instead_of_failing(self):
        model, session = self._model()
        session.run = MagicMock(side_effect=RuntimeError("shape mismatch"))
        model.side_effect = lambda x: np.array([0.3])
        vad = StreamingVAD(model)
        self.assertAlmostEqual(vad(np.zeros(FRAME)), 0.3, places=5)
        self.assertEqual(vad.kind, "stateless")

    @unittest.skipUnless(importlib.util.find_spec("faster_whisper") and importlib.util.find_spec("onnxruntime"),
                         "needs faster-whisper + onnxruntime")
    def test_real_silero_hears_quiet_speech(self):
        """
        4 s of real speech (public domain) at the measured quiet-mic level plus noise, through the real
        Silero model: the old per-frame calls found ~2% of the speech, gain + streaming finds ~95%.
        """
        from faster_whisper.vad import get_vad_model
        with wave.open(str(DATA / "speech_jfk_4s.wav"), "rb") as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        x = x[: len(x) // FRAME * FRAME]
        model = get_vad_model()
        reference = np.asarray(model(x)).reshape(-1) > 0.5          # whole clip in one call: the truth
        frames = x.reshape(-1, FRAME)
        level = np.median(np.sqrt((frames[reference] ** 2).mean(axis=1)))
        rng = np.random.default_rng(0)
        quiet = (frames * (0.004 / level) + rng.normal(0, 0.0008, frames.shape)).astype(np.float32)
        if StreamingVAD(model).kind == "stateless":
            self.skipTest("this faster-whisper has neither VAD API")

        def detect(chunks, agc, vad):
            out = []
            for f in chunks:
                g = agc.process(f)
                out.append(is_speech(vad(g), rms(g), agc.noise_after_gain))
            return np.array(out)
        old = np.array([float(np.asarray(model(f)).reshape(-1)[0]) >= 0.35 for f in quiet])
        new = detect(quiet, InputAGC(), StreamingVAD(model))
        self.assertLess(old[reference].mean(), 0.2)                # the bug, as measured on the laptop
        self.assertGreater(new[reference].mean(), 0.85)
        noise_only = rng.normal(0, 0.0008, (94, FRAME)).astype(np.float32)   # 3 s of an empty room
        self.assertLess(detect(noise_only, InputAGC(), StreamingVAD(model)).mean(), 0.05)


class TestCleanTranscript(unittest.TestCase):
    def test_collapses_a_phrase_said_twice(self):
        self.assertEqual(clean_transcript("open notepad, open notepad"), "open notepad")
        self.assertEqual(clean_transcript("Go back, go back, go."), "go back")
        self.assertEqual(clean_transcript("bye bye"), "bye")
        self.assertEqual(clean_transcript("MXB, open notepad, open notepad."), "mxb open notepad")
        self.assertEqual(clean_transcript("hey MXB open chrome open chrome"), "hey mxb open chrome")

    def test_drops_whisper_noise_loops(self):
        self.assertIsNone(clean_transcript("open app, open app, open app, open app, open app"))
        self.assertIsNone(clean_transcript("go, go, go"))
        self.assertIsNone(clean_transcript("Thank you. Thank you. Thank you. Thank you."))
        self.assertIsNone(clean_transcript("MXB open app open app open app open app"))

    def test_repeated_stop_or_no_is_never_dropped(self):
        self.assertEqual(clean_transcript("Stop! Stop! Stop!"), "stop")
        self.assertEqual(clean_transcript("no no no no"), "no")
        self.assertEqual(clean_transcript("cancel, cancel, cancel"), "cancel")

    def test_keeps_normal_commands(self):
        for text in ("MXB, open Chrome.", "very very good", "turn the volume up to 50", "open chrome then open notepad"):
            self.assertEqual(clean_transcript(text), text)

    def test_empty(self):
        for text in (None, "", " ", "a", "..."):
            self.assertIsNone(clean_transcript(text))


class TestWhisperOptions(unittest.TestCase):
    def test_hotwords_only_when_asked_and_supported(self):
        class New:
            def transcribe(self, audio, beam_size=5, hotwords=None):
                pass

        class Old:
            def transcribe(self, audio, beam_size=5, initial_prompt=None):
                pass
        self.assertEqual(whisper_options(New()), {})                          # off by default
        self.assertEqual(whisper_options(New(), "MXB Notepad"), {"hotwords": "MXB Notepad"})
        self.assertEqual(whisper_options(Old(), "MXB Notepad"), {})
        self.assertEqual(whisper_options(object(), "MXB"), {})

    def test_audio_pipeline_uses_the_helpers(self):
        """engine/audio.py needs PortAudio to import, so check its wiring from the source."""
        source = (Path(__file__).parent.parent / "engine" / "audio.py").read_text(encoding="utf-8")
        for needed in ("StreamingVAD(", "self.agc.process(chunk, adapt=", "is_speech(", "clean_transcript(",
                       "initial_prompt=None", "barge_detector.update(speech_prob, raw_rms)"):
            self.assertIn(needed, source)
        self.assertNotIn("Desktop commands: open app", source)
        self.assertNotIn("vad_model(chunk)", source)


class TestWakeWordFillers(unittest.TestCase):
    def setUp(self):
        self.gate = WakeWordGate(mode="wake_word", follow_up_seconds=10)

    def check(self, text, expected):
        self.gate.disengage()
        self.assertEqual(self.gate.process(text), expected, text)

    def test_fillers_before_the_wake_word(self):
        self.check("Ahh, MXB.", "")
        self.check("um, hey MXB open chrome", "open chrome")
        self.check("Okay so MXB, what's the time", "what's the time")

    def test_wake_word_at_the_end(self):
        self.check("open chrome, MXB.", "open chrome")
        self.check("What's the weather MXB?", "What's the weather")

    def test_how_whisper_misspells_mxb(self):
        self.check("MXP open notepad", "open notepad")
        self.check("Emexbee, open notepad", "open notepad")
        self.check("M X B open notepad", "open notepad")
        self.check("AMX-B, what time is it?", "what time is it?")          # Whisper's "Hey MXB" on a real PC

    def test_wake_word_starting_a_later_sentence(self):
        """Background talk or a TV runs into the command; Whisper still marks the sentence break."""
        self.check("and that's the news for today. MXB, open notepad.", "open notepad.")
        self.check("Turn it off. Hey MXB what's the time?", "what's the time?")
        self.check("I saw the MXB demo. It was good.", None)

    def test_still_ignores_mentions_mid_sentence(self):
        self.check("so we tested the MXB app yesterday", None)
        self.check("I think we should order pizza tonight", None)

    def test_variants_only_for_the_default_name(self):
        gate = WakeWordGate(mode="wake_word", wake_words=["jarvis"])
        self.assertIsNone(gate.process("MXP open notepad"))
        self.assertEqual(gate.process("hmm, Jarvis open notepad"), "open notepad")


class TestAppLauncher(unittest.TestCase):
    def launcher(self, shortcuts=None, store=None):
        with patch.object(SmartAppLauncher, "_index_start_menu", lambda self: None):
            app = SmartAppLauncher()
        app.shortcuts = dict(shortcuts or {})
        app._store_apps = dict(store or {})
        return app

    def test_misheard_names_open_windows_tools(self):
        app = self.launcher()
        for said in ("notebook", "Notepad.", "the notepad app", "note pad"):
            with patch("os.startfile", create=True) as start:
                self.assertEqual(app.launch(said), "Launched notepad")
            start.assert_called_once_with("notepad")
        with patch("os.startfile", create=True) as start:
            app.launch("calculater")
        start.assert_called_once_with("calc")

    def test_users_own_app_wins_over_a_correction(self):
        app = self.launcher({"notebook": r"C:\Start Menu\Notebook.lnk"})
        with patch("os.startfile", create=True) as start:
            self.assertEqual(app.launch("Notebook"), "Launched 'notebook'")
        start.assert_called_once_with(r"C:\Start Menu\Notebook.lnk")

    def test_fuzzy_shortcut_match(self):
        app = self.launcher({"google chrome": r"C:\x\Google Chrome.lnk", "zoom": r"C:\x\Zoom.lnk"})
        with patch("os.startfile", create=True) as start:
            self.assertEqual(app.launch("crome"), "Launched 'google chrome'")
        start.assert_called_once_with(r"C:\x\Google Chrome.lnk")

    def test_store_apps_without_shortcuts(self):
        app = self.launcher(store={"whatsapp": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"})
        with patch("utils.app_launcher.subprocess.Popen") as popen:
            self.assertEqual(app.launch("whats app"), "Launched 'whatsapp'")
        popen.assert_called_once_with(["explorer.exe", "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"])

    def test_unknown_app(self):
        app = self.launcher({"zoom": r"C:\x\Zoom.lnk"}, {"spotify": "SpotifyAB.SpotifyMusic!Spotify"})
        self.assertEqual(app.launch("zzzqqq"), "Could not find an app matching 'zzzqqq'")
        self.assertEqual(self.launcher().launch("zzzqqq"), "No applications indexed.")
        self.assertEqual(app.launch("  "), "Which app should I open?")

    def test_get_startapps_parsing(self):
        one = json.dumps({"Name": "WhatsApp", "AppID": "W!App"})
        many = json.dumps([{"Name": "Spotify", "AppID": "S!App"}, {"Name": "", "AppID": "x"}, {"Name": "Calc"}])
        self.assertEqual(parse_start_apps(one), {"whatsapp": "W!App"})
        self.assertEqual(parse_start_apps(many), {"spotify": "S!App"})
        self.assertEqual(parse_start_apps("not json"), {})
        self.assertEqual(parse_start_apps(""), {})


class TestCompactPlannerPrompt(unittest.TestCase):
    def test_relevant_tools(self):
        names = relevant_actions("turn up the volume")
        self.assertIn("set_volume", names)
        self.assertTrue(set(CORE_ACTIONS) <= set(names))
        self.assertLessEqual(len(names), len(CORE_ACTIONS) + 12)
        self.assertIn("scam_check", relevant_actions("is this message a scam"))
        self.assertIn("set_reminder", relevant_actions("remind me to call mom at 5"))
        self.assertTrue(set(relevant_actions("")) == set(CORE_ACTIONS))
        self.assertTrue(set(relevant_actions("open notebook")) <= set(action_names()))

    def test_prompt_is_a_fraction_of_the_full_one(self):
        names = relevant_actions("turn up the volume")
        small, full = planner_system_prompt(only=names), planner_system_prompt()
        self.assertLess(len(small), len(full) * 0.4)
        self.assertIn("set_volume", small)
        self.assertNotIn("scam_check", small)
        self.assertLess(estimate_tokens(small, json.dumps(plan_tool_schema(names=names))), 2000)
        enum = plan_tool_schema(names=names)["function"]["parameters"]["properties"]["plan"]["items"]["properties"]["action"]["enum"]
        self.assertEqual(enum, names)

    def _router(self, cloud: bool, **llm_cfg):
        from engine.router import IntentRouter
        router = IntentRouter.__new__(IntentRouter)
        router.config = {"llm": llm_cfg}
        router.llm = MagicMock()
        router.llm.cloud_available.return_value = cloud
        router.tts = MagicMock()
        router.tts.speaking_enabled.return_value = False
        return router

    def test_router_sends_local_models_the_compact_prompt(self):
        router = self._router(cloud=False)
        router.llm.plan_with_tools.return_value = {"reply": "Turning it up.", "plan": [{"action": "set_volume", "target": "80"}]}
        data, spoke = router._plan("User Command: 'turn up the volume'", query="turn up the volume")
        self.assertEqual(data["plan"][0]["action"], "set_volume")
        system, _prompt, tool = router.llm.plan_with_tools.call_args.args
        self.assertLess(len(system), len(planner_system_prompt()) * 0.4)
        self.assertLessEqual(len(tool["function"]["parameters"]["properties"]["plan"]["items"]["properties"]["action"]["enum"]),
                             len(CORE_ACTIONS) + 12)

    def test_cloud_models_keep_every_tool(self):
        self.assertIsNone(self._router(cloud=True).planner_tools("turn up the volume"))
        self.assertIsNone(self._router(cloud=False, compact_local_prompt=False).planner_tools("turn up the volume"))
        self.assertIsNone(self._router(cloud=False).planner_tools(None))

    def test_failure_messages_say_what_went_wrong(self):
        router = self._router(cloud=False)
        router.llm.local_model = "llama3.2:1b"
        router.llm.last_failure = "timeout"
        self.assertIn("llama3.2:1b", router._no_plan_message())
        self.assertIn("too slow", router._no_plan_message())
        router.llm.last_failure = "offline"
        self.assertIn("Start Ollama", router._no_plan_message())


class TestLocalModelFailFast(unittest.TestCase):
    def setUp(self):
        self.nvidia = patch("engine.llm_client.CredentialsManager.get_nvidia_api_key", return_value=None)
        self.nvidia.start()
        self.addCleanup(self.nvidia.stop)

    def test_one_timeout_does_not_become_three(self):
        client = LLMClient({"llm": {"local_timeout_sec": 40}})
        with patch("engine.llm_client.requests.post", side_effect=requests.exceptions.ReadTimeout("read timed out")) as post:
            t0 = time.monotonic()
            self.assertEqual(client.stream_chat("sys", "turn up the volume"), "")
            self.assertIsNone(client.plan_with_tools("sys", "x", plan_tool_schema()))
            self.assertIsNone(client.chat_json("sys", "x"))
        self.assertEqual(post.call_count, 1)                    # the router's next two attempts didn't wait
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(client.last_failure, "timeout")
        self.assertTrue(client.local_paused())

    def test_retries_after_the_pause(self):
        client = LLMClient({"llm": {"local_retry_after_sec": 0}})
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"message": {"content": '{"reply": "hi", "plan": []}'}}
        with patch("engine.llm_client.requests.post", side_effect=[requests.exceptions.ConnectionError("refused"), ok]) as post:
            self.assertIsNone(client.chat_json("sys", "x"))
            self.assertEqual(client.last_failure, "offline")
            self.assertEqual(client.chat_json("sys", "x"), {"reply": "hi", "plan": []})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(client.last_failure, "")

    def test_bad_reply_is_not_an_outage(self):
        client = LLMClient({})
        bad = MagicMock(status_code=500, text="boom")
        with patch("engine.llm_client.requests.post", return_value=bad):
            self.assertIsNone(client.chat_json("sys", "x"))
        self.assertFalse(client.local_paused())

    def test_paused_call_raises_its_own_error(self):
        client = LLMClient({})
        client._local_failed_at, client.last_failure = time.monotonic(), "timeout"
        with self.assertRaises(LocalModelPaused):
            client._post_ollama({"messages": []})

    def test_every_ollama_call_uses_the_same_context_size(self):
        client = LLMClient({"llm": {"num_ctx": 8192}})
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"message": {"content": "{}"}}
        ok.iter_lines.return_value = []
        ok.__enter__ = lambda s: s
        ok.__exit__ = lambda s, *a: False
        with patch("engine.llm_client.requests.post", return_value=ok) as post:
            client.chat("sys", "x")
            client.plan_with_tools("sys", "x", plan_tool_schema())
            client.stream_chat("sys", "x")
        payloads = [c.kwargs["json"] for c in post.call_args_list]
        self.assertEqual(len(payloads), 3)
        self.assertEqual({p["options"]["num_ctx"] for p in payloads}, {8192})   # a change reloads the model
        self.assertEqual({p["keep_alive"] for p in payloads}, {"2h"})

    def test_oversized_prompt_is_logged(self):
        client = LLMClient({"llm": {"num_ctx": 512}})
        with patch("engine.llm_client.requests.post", return_value=MagicMock(status_code=500, text="")), \
                patch("engine.llm_client.log.warning") as warn:
            client.chat("x" * 4000, "y")
        self.assertTrue(any("num_ctx=512" in str(c.args[0]) for c in warn.call_args_list))

    def test_warm_up_loads_the_model(self):
        client = LLMClient({"llm": {"local_model": "llama3.2:1b", "num_ctx": 4096}})
        with patch("engine.llm_client.requests.post", return_value=MagicMock(status_code=200)) as post:
            self.assertTrue(client.warm_up())
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        self.assertTrue(url.endswith("/api/generate"))
        self.assertEqual((payload["model"], payload["prompt"], payload["options"]["num_ctx"]), ("llama3.2:1b", "", 4096))
        with patch("engine.llm_client.requests.post", side_effect=requests.exceptions.ConnectionError("no ollama")):
            self.assertFalse(client.warm_up())
        self.assertFalse(client.local_paused())                 # warm-up never blocks real requests

    def test_cloud_available(self):
        self.assertFalse(LLMClient.cloud_available())
        with patch("engine.llm_client.CredentialsManager.get_nvidia_api_key", return_value="nvapi-x"):
            self.assertTrue(LLMClient.cloud_available())


if __name__ == "__main__":
    unittest.main()
