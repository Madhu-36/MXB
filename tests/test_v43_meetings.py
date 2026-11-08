"""v4.3 meeting copilot: synthetic audio through the real segmenter, session, notes and copilot."""
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

import tests._stubs  # noqa: F401
from engine.meetings import (
    MeetingCopilot, MeetingSession, Segmenter, notes_markdown, safe_title, spoken_notes, summarize, to_mono_16k,
)

SR = 16000


def tone(seconds, amp, freq=220.0):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SR), dtype=np.float32)


class ArraySource:
    """Plays a prepared signal into the session in 100 ms blocks when started."""

    def __init__(self, signal):
        self.signal, self.stopped = signal, False

    def start(self, on_audio):
        for i in range(0, len(self.signal), 1600):
            on_audio(self.signal[i:i + 1600])

    def stop(self):
        self.stopped = True


def by_amplitude(table):
    """Fake speech engine: identifies the 'utterance' by its loudness."""
    def transcribe(audio):
        peak = float(np.max(np.abs(audio)))
        return min(table.items(), key=lambda kv: abs(kv[0] - peak))[1]
    return transcribe


class FakeLLM:
    def __init__(self, notes):
        self.notes, self.calls = notes, []

    def chat_json(self, system, user, max_tokens=None, image_png=None):
        self.calls.append((system, user))
        return self.notes


NOTES = {"summary": "The budget was approved and Ravi owns the report.", "decisions": ["Budget approved"],
         "action_items": [{"owner": "Ravi", "task": "send the report", "due": "Friday"}, "book the hall"],
         "questions": ["Who presents?"]}


class TestAudioPieces(unittest.TestCase):
    def test_mono_resample(self):
        stereo = np.stack([np.ones(48000), np.zeros(48000)], axis=1).astype(np.float32).reshape(-1)
        out = to_mono_16k(stereo, 48000, 2)
        self.assertEqual(len(out), 16000)
        self.assertAlmostEqual(float(out.mean()), 0.5, places=3)
        self.assertEqual(len(to_mono_16k(np.ones(16000), 16000)), 16000)

    def test_segmenter_cuts_at_pauses(self):
        seg = Segmenter()
        signal = np.concatenate([silence(0.5), tone(1.0, 0.2), silence(1.0), tone(0.6, 0.3), silence(1.0),
                                 tone(0.1, 0.3), silence(1.0)])
        out = []
        for i in range(0, len(signal), 1600):
            out += seg.feed(signal[i:i + 1600])
        out += seg.flush()
        self.assertEqual(len(out), 2)                       # the 0.1 s blip is ignored
        self.assertAlmostEqual(out[0][0], 0.5, delta=0.06)
        self.assertAlmostEqual(out[1][0], 2.5, delta=0.06)

    def test_long_speech_is_split(self):
        seg = Segmenter(max_segment_s=15.0)
        out = seg.feed(tone(20.0, 0.2)) + seg.flush()
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(len(out[0][1]) / SR, 15.0, delta=0.05)

    def test_trailing_silence_is_trimmed(self):
        seg = Segmenter()
        (start, audio), = seg.feed(np.concatenate([tone(1.0, 0.2), silence(1.0)]))
        self.assertLess(len(audio) / SR, 1.0 + 0.35)

    def test_titles(self):
        self.assertEqual(safe_title('Sprint: review / "Q4"'), "Sprint review Q4")
        self.assertEqual(safe_title(""), "Meeting")


class TestSessionAndNotes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

    def sources(self, echo=False):
        others = np.concatenate([silence(0.3), tone(1.2, 0.2), silence(1.0), tone(1.0, 0.4), silence(1.0)])
        you = np.concatenate([silence(1.8), tone(1.0, 0.3), silence(0.8)])
        if echo:   # no headset: the mic also hears the other side's first sentence
            you = np.concatenate([silence(0.3), tone(1.2, 0.2), silence(1.0)])
        return {"Others": ArraySource(others), "You": ArraySource(you)}

    TEXT = {0.2: "the budget is approved", 0.3: "great I will tell the team", 0.4: "Ravi will send the report by Friday"}

    def test_two_speakers_in_time_order(self):
        session = MeetingSession("Sprint review", by_amplitude(self.TEXT), self.folder, self.sources())
        session.start()
        session.stop()
        self.assertEqual([sp for _, sp, _ in session.lines], ["Others", "You", "Others"])
        self.assertEqual(session.lines[0][2], "the budget is approved")
        saved = session.path.read_text(encoding="utf-8")
        self.assertIn("**[00:00] Others:** the budget is approved", saved)
        self.assertLess(saved.index("great I will tell the team"), saved.index("Ravi will send"))

    def test_echo_from_speakers_is_dropped(self):
        session = MeetingSession("x", by_amplitude(self.TEXT), self.folder, self.sources(echo=True))
        session.start()
        session.stop()
        self.assertEqual([sp for _, sp, _ in session.lines].count("You"), 0)

    def test_summary_map_reduce_and_markdown(self):
        llm = FakeLLM(NOTES)
        transcript = "\n".join(f"[00:{i:02d}] Others: word " * 30 for i in range(60))
        notes = summarize(transcript, llm, chunk_words=1000)
        self.assertGreater(len(llm.calls), 2)                # several chunks + one merge
        self.assertIn("<<UNTRUSTED meeting transcript", llm.calls[0][1])
        md = notes_markdown(notes)
        self.assertIn("- [ ] **Ravi**: send the report (due Friday)", md)
        self.assertIn("- [ ] book the hall", md)
        self.assertIn("## Open questions", md)
        self.assertIn("2 action items: Ravi to send the report by Friday; book the hall.", spoken_notes(notes))
        self.assertIsNone(summarize(transcript, None))


class ManualSource:
    """A device that only sends audio when the test says so (like Windows loopback, silent = no data)."""

    def start(self, on_audio):
        self.send = on_audio

    def stop(self):
        pass


class TestQuietStreams(unittest.TestCase):
    def test_a_stream_that_goes_quiet_is_padded_on_the_wall_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = {"t": 1000.0}
            src = ManualSource()
            session = MeetingSession("Lecture", by_amplitude({0.2: "first point", 0.4: "second point"}), Path(tmp),
                                     {"Others": src}, clock=lambda: now["t"], tick=None)
            session.start()
            now["t"] += 1.0
            src.send(tone(1.0, 0.2))                 # speech, then the speakers fall silent: no more blocks
            now["t"] += 2.0
            session.fill_gaps()                      # what the 0.25 s ticker does in the app
            deadline = time.time() + 3
            while not session.lines and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual([(round(t), tx) for t, _, tx in session.lines], [(0, "first point")])   # not stuck
            now["t"] += 7.0                          # 7 s of nothing, then the next sentence arrives
            src.send(tone(1.0, 0.4))
            now["t"] += 2.0
            session.fill_gaps()
            session.stop(timeout=5)
            times = [round(t) for t, _, _ in session.lines]
            self.assertEqual(times, [0, 9])          # wall-clock time, not "1 s after the first sentence"

    def test_continuous_streams_are_not_padded(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = {"t": 50.0}
            src = ManualSource()
            session = MeetingSession("Call", lambda audio: "", Path(tmp), {"You": src}, clock=lambda: now["t"], tick=None)
            session.start()
            for _ in range(30):                      # 3 s of 100 ms blocks arriving on time
                now["t"] += 0.1
                src.send(silence(0.1))
                session.fill_gaps()
            session.stop(timeout=5)
            self.assertAlmostEqual(session._fed["You"], 3.0, places=3)


class TestCopilot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.indexed = []
        self.llm = FakeLLM(NOTES)
        signal = np.concatenate([silence(0.3), tone(1.0, 0.4), silence(1.0)])
        self.copilot = MeetingCopilot({}, transcriber=by_amplitude({0.4: "Ravi will send the report by Friday"}),
                                      llm_getter=lambda: self.llm, folder=self.folder, indexer=self.indexed.append,
                                      source_factory=lambda: ({"Others": ArraySource(signal)}, ""))

    def test_full_meeting(self):
        self.assertIn("I'm not taking meeting notes", self.copilot.stop())
        started = self.copilot.start("Budget sync")
        self.assertIn("let everyone know", started)
        self.assertIn("already taking notes", self.copilot.start("again"))
        time.sleep(0.2)
        self.assertEqual(self.copilot.status("what did they just say"), "Ravi will send the report by Friday")
        done = self.copilot.stop()
        self.assertIn("Saved 1 minute of notes", done)
        self.assertIn("2 action items", done)
        saved = self.copilot.last_path.read_text(encoding="utf-8")
        self.assertIn("## Action items", saved)
        self.assertEqual(self.indexed, [str(self.folder)])
        self.assertIn("Budget sync", self.copilot.list_meetings())
        self.assertIn("budget was approved", self.copilot.recap("last"))

    def test_without_ai_brain(self):
        copilot = MeetingCopilot({}, transcriber=lambda a: "hello", llm_getter=lambda: None, folder=self.folder,
                                 source_factory=lambda: ({"Others": ArraySource(np.concatenate([tone(1.0, 0.3), silence(1.0)]))}, ""))
        copilot.start("Standup")
        self.assertNotIn("action items", copilot.stop())
        self.assertIn("Summary unavailable", copilot.last_path.read_text(encoding="utf-8"))
        self.assertIn("no summary yet", copilot.recap("standup"))

    def test_closing_mxb_keeps_the_transcript_without_waiting_for_ai(self):
        self.copilot.start("Late call")
        time.sleep(0.2)
        self.assertIn("Saved the transcript", self.copilot.stop(summarize_notes=False, timeout=5))
        saved = self.copilot.last_path.read_text(encoding="utf-8")
        self.assertIn("Ravi will send the report by Friday", saved)
        self.assertIn("MXB was closing", saved)
        self.assertNotIn("## Action items", saved)
        self.assertEqual(self.indexed, [])

    def test_recap_finds_a_meeting_by_topic(self):
        (self.folder / "2026-11-01 1000 Hackathon planning.md").write_text(
            "# Hackathon planning\n\n## Summary\nTeam picked the scam-detection idea.\n", encoding="utf-8")
        (self.folder / "2026-11-02 1000 Placement prep.md").write_text(
            "# Placement prep\n\n## Summary\nMock interviews on Friday.\n", encoding="utf-8")
        self.assertIn("scam-detection idea", self.copilot.recap("the hackathon"))
        self.assertIn("couldn't find a meeting about 'cricket'", self.copilot.recap("cricket"))
        self.assertIn("Mock interviews", self.copilot.recap("placement prep"))

    def test_source_failure_is_reported(self):
        def boom():
            raise RuntimeError("no audio device")
        copilot = MeetingCopilot({}, transcriber=lambda a: "", folder=self.folder, source_factory=boom)
        self.assertIn("couldn't start recording: no audio device", copilot.start("x"))
        self.assertFalse(copilot.active)


if __name__ == "__main__":
    unittest.main()
