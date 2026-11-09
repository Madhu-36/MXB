"""
v4.2 pixel grounding. The fake vision model really "looks": it decodes the JPEG it was sent,
finds the red square and answers in the requested output format, so resizing, encoding,
parsing, scaling back, the zoom pass and offsets are all tested end to end.
"""
import base64
import io
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image, ImageDraw

import tests._stubs  # noqa: F401
from engine.grounding import (
    NVIDIA_URL, Grounder, GroundingError, parse_location, resolve_mode, to_pixels, where_on_screen,
)
from safety.injection import scope_for_goal, scoped

SQUARE = (1800, 900, 1830, 930)   # on a 2560x1440 screen -> center (1815, 915)


def screen(width=2560, height=1440, square=SQUARE):
    img = Image.new("RGB", (width, height), "white")
    if square:
        ImageDraw.Draw(img).rectangle(square, fill=(230, 20, 20))
    return img


class Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data


class FakeVision:
    """Finds red pixels in the image it receives and replies like a grounding model would."""

    def __init__(self, style="relative", ollama_models=("qwen3-vl:4b",), status=200):
        self.style, self.models, self.status = style, list(ollama_models), status
        self.sizes, self.posts = [], []

    def get(self, url, timeout=None):
        return Resp(200, {"models": [{"name": m} for m in self.models]})

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        if self.status != 200:
            return Resp(self.status, {}, "unauthorized")
        if "images" in json["messages"][1]:
            b64 = json["messages"][1]["images"][0]
        else:
            b64 = json["messages"][1]["content"][1]["image_url"]["url"].split(",", 1)[1]
        img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        w, h = img.size
        self.sizes.append((w, h))
        px = img.load()
        reds = [(x, y) for y in range(0, h) for x in range(0, w) if px[x, y][0] > 180 and px[x, y][1] < 90 and px[x, y][2] < 90]
        if not reds:
            reply = '{"found": false}'
        else:
            cx = sum(p[0] for p in reds) / len(reds)
            cy = sum(p[1] for p in reds) / len(reds)
            if self.style == "relative":
                reply = f'{{"found": true, "point_2d": [{round(cx / w * 1000)}, {round(cy / h * 1000)}]}}'
            elif self.style == "absolute":
                reply = f"Thought: the red one.\nAction: click(start_box='({round(cx)},{round(cy)})')"
            else:   # Qwen3-VL list-of-boxes style
                x1, y1 = min(p[0] for p in reds), min(p[1] for p in reds)
                x2, y2 = max(p[0] for p in reds), max(p[1] for p in reds)
                box = [round(x1 / w * 1000), round(y1 / h * 1000), round(x2 / w * 1000), round(y2 / h * 1000)]
                reply = f'```json\n[{{"bbox_2d": {box}, "label": "red square"}}]\n```'
        if "images" in json["messages"][1]:
            return Resp(200, {"message": {"content": reply}})
        return Resp(200, {"choices": [{"message": {"content": reply}}]})


class TestParsing(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_location('{"found": true, "point_2d": [500, 250]}')["point"], (500.0, 250.0))
        self.assertEqual(parse_location('[{"bbox_2d": [10, 20, 30, 40], "label": "x"}]')["box"], (10.0, 20.0, 30.0, 40.0))
        self.assertIs(parse_location('{"found": false}')["found"], False)
        self.assertEqual(parse_location("Action: click(start_box='(523,341)')")["point"], (523.0, 341.0))
        self.assertEqual(parse_location("<|box_start|>(10,20,30,40)<|box_end|>")["box"], (10.0, 20.0, 30.0, 40.0))
        molmo = parse_location('<point x="12.5" y="40.0" alt="gear">gear</point>')
        self.assertTrue(molmo["percent"])
        self.assertEqual(parse_location('```json\n{"x": 3, "y": 4}\n```')["point"], (3.0, 4.0))
        self.assertIs(parse_location("Sorry, I cannot find that button.")["found"], False)
        self.assertIsNone(parse_location("hmm"))
        self.assertIsNone(parse_location(""))

    def test_coordinate_modes(self):
        self.assertEqual(to_pixels({"point": (500, 500)}, "auto", 1280, 720)[0], (640, 360))
        self.assertEqual(resolve_mode({"point": (1500, 300)}, "auto"), "absolute")
        self.assertEqual(to_pixels({"point": (1200, 300)}, "auto", 1288, 728)[0], (1200, 300))
        self.assertEqual(to_pixels({"point": (0.25, 0.5)}, "auto", 1000, 800)[0], (250, 400))
        self.assertEqual(to_pixels({"point": (10.0, 50.0), "percent": True}, "auto", 1000, 800)[0], (100, 400))
        self.assertEqual(to_pixels({"point": None, "box": (100, 100, 300, 200)}, "relative_1000", 1000, 1000)[0], (200, 150))
        self.assertIsNone(to_pixels({"point": (1200, 10)}, "relative_1000", 1000, 1000))   # off-image -> rejected
        self.assertEqual(where_on_screen(2400, 100, 2560, 1440), "top right")
        self.assertEqual(where_on_screen(1280, 720, 2560, 1440), "center")


class TestGrounder(unittest.TestCase):
    def near(self, hit, x=1815, y=915, tol=4):
        self.assertIsNotNone(hit)
        self.assertLessEqual(abs(hit.x - x), tol, hit)
        self.assertLessEqual(abs(hit.y - y), tol, hit)

    def test_relative_with_zoom_on_a_wide_screen(self):
        http = FakeVision("relative")
        hit = Grounder({}, http=http, key_provider=lambda: None).locate("the red square", screen())
        self.near(hit)
        self.assertEqual(hit.provider, "ollama")
        self.assertEqual(hit.model, "qwen3-vl:4b")
        self.assertEqual(http.sizes[0], (1280, 720))       # first look: downscaled full screen
        self.assertEqual(len(http.sizes), 2)               # second look: the zoomed crop
        self.assertLess(http.sizes[1][0], 1280)

    def test_absolute_ui_tars_style(self):
        http = FakeVision("absolute")
        g = Grounder({"grounding": {"coord_mode": "absolute", "zoom_refine": False}}, http=http, key_provider=lambda: None)
        hit = g.locate("the red square", screen())
        self.near(hit)
        w, h = http.sizes[0]
        self.assertEqual((w % 28, h % 28), (0, 0))          # sized so the model's own resize is a no-op

    def test_qwen3_box_list_and_offset(self):
        g = Grounder({"grounding": {"zoom_refine": False}}, http=FakeVision("boxes"), key_provider=lambda: None)
        hit = g.locate("the red square", screen(), offset=(-2560, 0))   # e.g. a monitor left of the primary
        self.near(hit, x=1815 - 2560)
        self.assertEqual(len(hit.box), 4)

    def test_not_found(self):
        g = Grounder({}, http=FakeVision("relative"), key_provider=lambda: None)
        self.assertIsNone(g.locate("the red square", screen(square=None)))

    def test_nvidia_when_no_local_model(self):
        http = FakeVision("relative", ollama_models=())
        g = Grounder({"grounding": {"zoom_refine": False}}, http=http, key_provider=lambda: "nvapi-test")
        hit = g.locate("the red square", screen())
        self.near(hit)
        url, body, headers = http.posts[0]
        self.assertEqual(url, NVIDIA_URL)
        self.assertEqual(body["model"], "qwen/qwen3.5-122b-a10b")
        self.assertTrue(body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(headers["Authorization"], "Bearer nvapi-test")

    def test_no_provider_and_errors(self):
        g = Grounder({}, http=FakeVision(ollama_models=()), key_provider=lambda: None)
        self.assertFalse(g.available())
        with self.assertRaisesRegex(GroundingError, "ollama pull qwen3-vl:4b"):
            g.locate("x", screen())
        bad = Grounder({"grounding": {"provider": "nvidia"}}, http=FakeVision(status=401), key_provider=lambda: "k")
        with self.assertRaisesRegex(GroundingError, "401"):
            bad.locate("x", screen())
        with self.assertRaisesRegex(GroundingError, "What should I look for"):
            bad.locate("  ", screen())
        off = Grounder({"grounding": {"enabled": False}}, http=FakeVision(), key_provider=lambda: None)
        self.assertFalse(off.available())


class TestExecutorVisual(unittest.TestCase):
    def setUp(self):
        for target in ("MouseController", "KeyboardExtended", "ScreenVision", "SmartAppLauncher"):
            p = patch(f"engine.executor.{target}")
            p.start()
            self.addCleanup(p.stop)
        from engine.executor import OSExecutionManager
        from engine.grounding import Grounding
        self.ex = OSExecutionManager(config={})
        self.ex.audit = MagicMock()
        self.ex.screen.capture_screen_image.return_value = screen()
        self.ex._grounder = MagicMock()
        self.ex._grounder.locate.return_value = Grounding(1815, 915, None, "ollama", "qwen3-vl:4b", "{}")
        self.asked = []
        self.ex.confirm_callback = lambda q: (self.asked.append(q), False)[1]

    def test_visual_actions(self):
        self.assertEqual(self.ex.execute_action("click_visual", "the gear icon"), "Clicked 'the gear icon' at 1815, 915.")
        self.ex.mouse.left_click.assert_called_with(1815, 915)
        self.ex.execute_action("double_click_visual", "the red folder")
        self.ex.mouse.double_click.assert_called_with(1815, 915)
        self.assertEqual(self.ex.execute_action("type_visual", "the search field :: cats"), "Typed into 'the search field'.")
        self.ex.keyboard.type_text.assert_called_with("cats")
        self.assertIn("right of the screen", self.ex.execute_action("locate_visual", "the gear icon"))
        self.ex._grounder.locate.return_value = None
        self.assertIn("can't see 'the gear icon'", self.ex.execute_action("click_visual", "the gear icon"))
        self.ex._grounder.locate.side_effect = GroundingError("Visual clicking needs a vision model")
        self.assertIn("needs a vision model", self.ex.execute_action("click_visual", "x"))

    def test_click_element_falls_back_to_looking(self):
        self.ex._uia = MagicMock()
        self.ex._uia.available.return_value = False
        self.ex.screen.find_text_coordinates.return_value = None
        with patch.object(type(self.ex), "_grounding_fallback_on", return_value=True):
            res = self.ex.execute_action("click_element", "settings gear")
        self.assertTrue(res.endswith("(found by looking)"), res)
        with patch.object(type(self.ex), "_grounding_fallback_on", return_value=False):
            self.assertIn("Could not find", self.ex.execute_action("click_element", "settings gear"))

    def test_agent_risky_visual_click_asks(self):
        with scoped(scope_for_goal("open my notes")):
            res = self.ex.execute_action("click_visual", "the Send button")
        self.assertTrue(res.startswith("Cancelled"), res)
        self.assertIn("'the Send button'", self.asked[0])
        self.ex.mouse.left_click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
