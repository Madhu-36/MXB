"""Router v3 fast-paths: search boxes, UI fields, hardware, files, power — with case preservation."""
import unittest
from unittest.mock import MagicMock

import tests._stubs  # noqa: F401
from engine.router import IntentRouter

CASES = [
    # The exact example from the feature request
    ("Go to the search box and enter Cute Cats and press Enter.", ("search_on_screen", "Cute Cats")),
    ("go to the search box and type hello world", ("type_into", "search :: hello world")),
    ("go to the YouTube search bar and type Lofi Hip Hop and hit enter", ("search_on_screen", "youtube :: Lofi Hip Hop")),
    ("type Hello World in the search box and press enter", ("search_on_screen", "Hello World")),
    ("search Python tutorials in the search bar", ("search_on_screen", "Python tutorials")),
    ("type Srinivas@Example.com in the email field", ("type_into", "email :: Srinivas@Example.com")),
    ("click the search box", ("focus_search_box", "")),
    ("click the Submit button", ("click_element", "Submit")),
    ("turn on bluetooth", ("bluetooth_power", "on")),
    ("turn the bluetooth off", ("bluetooth_power", "off")),
    ("list my bluetooth devices", ("bluetooth_devices", "")),
    ("connect my boAt Airdopes", ("bluetooth_connect", "boAt Airdopes")),
    ("disconnect my headphones", ("bluetooth_disconnect", "headphones")),
    ("turn off wifi", ("wifi_power", "off")),
    ("connect to the wifi network Home_5G", ("wifi_connect", "Home_5G")),
    ("show wifi networks", ("wifi_networks", "")),
    ("set volume to 40", ("set_volume", "40")),
    ("mute the mic", ("mic_mute", "on")),
    ("set brightness to 70 percent", ("set_brightness", "70")),
    ("list usb devices", ("list_devices", "usb")),
    ("open bluetooth settings", ("open_settings", "bluetooth")),
    ("shut down the computer", ("power_action", "shutdown")),
    ("put the computer to sleep", ("power_action", "sleep")),
    ("cancel shutdown", ("power_action", "cancel")),
    ("give access to D drive", ("grant_file_access", "D drive")),
    ("give full file access", ("grant_file_access", "all")),
    ("find the file named Resume", ("find_files", "Resume")),
    ("find file budget in D drive", ("find_files", "budget :: D drive")),
    ("read file Notes.txt", ("read_file", "Notes.txt")),
    ("open the file Resume.pdf", ("open_path", "Resume.pdf")),
    ("delete the file old_notes.txt", ("delete_file", "old_notes.txt")),
    ("permanently delete the file junk.txt", ("delete_file", "junk.txt :: permanent")),
    ("move Report.pdf to documents", ("move_file", "Report.pdf :: documents")),
    ("rename file Draft.docx to Final", ("rename_file", "Draft.docx :: Final")),
    ("force close chrome", ("force_close_app", "chrome")),
    ("agent: reply to the latest email from Ravi", ("agent_task", "reply to the latest email from Ravi")),
    ("type Hello There", ("type_text", "Hello There")),
]


class TestCompanionRouter(unittest.TestCase):
    def setUp(self):
        self.exec = MagicMock()
        self.exec.execute_action.return_value = "ok"
        self.router = IntentRouter(executor=self.exec, tts=MagicMock())

    def test_fast_paths(self):
        for phrase, expected in CASES:
            with self.subTest(phrase=phrase):
                self.exec.reset_mock()
                self.router.route(phrase)
                self.assertEqual(self.exec.execute_action.call_args.args, expected)

    def test_existing_fast_paths_untouched(self):
        for phrase, expected in [("mute audio", ("media_control", "mute")), ("press enter", ("press_key", "enter")),
                                 ("snap top left", ("manage_window", "top_left")), ("open task manager", ("open_task_manager",))]:
            self.exec.reset_mock()
            self.router.route(phrase)
            self.assertEqual(self.exec.execute_action.call_args.args, expected, phrase)

    def test_clock_answers_locally(self):
        res = self.router.route("what time is it")
        self.assertIn("It's", res)
        self.exec.execute_action.assert_not_called()

    def test_window_moves_are_not_file_moves(self):
        self.exec.reset_mock()
        with unittest.mock.patch.object(self.router, "_route_to_llm", return_value="llm"):
            self.router.route("move this window to the left")
        for call in self.exec.execute_action.call_args_list:
            self.assertNotEqual(call.args[0], "move_file")

    def test_vault_secret_keeps_case(self):
        self.router.route("store secret github as AbC123xYz")
        self.exec.execute_action.assert_called_with("vault_store", "github::AbC123xYz")


if __name__ == "__main__":
    unittest.main()
