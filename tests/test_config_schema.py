import unittest
from utils.config_schema import ConfigSchema

class TestConfigSchema(unittest.TestCase):

    def test_default_config_is_valid(self):
        is_valid, validated, warnings = ConfigSchema.validate(ConfigSchema.DEFAULTS)
        self.assertTrue(is_valid)
        self.assertEqual(len(warnings), 0)
        self.assertEqual(validated["engine"]["vad_speech_prob_threshold"], 0.35)

    def test_empty_config_recovers_with_defaults(self):
        is_valid, validated, warnings = ConfigSchema.validate({})
        self.assertTrue(is_valid)
        self.assertIn("hotkeys", validated)
        self.assertIn("llm", validated)
        self.assertEqual(validated["llm"]["local_model"], "llama3.2:1b")

    def test_range_clamping_on_engine_parameters(self):
        bad_config = {
            "engine": {
                "vad_speech_prob_threshold": 99.0, # should clamp to 0.95
                "agc_target_level": -5.0,           # should clamp to 0.1
                "max_gain": 5000.0                 # should clamp to 100.0
            }
        }
        _, validated, _ = ConfigSchema.validate(bad_config)
        self.assertEqual(validated["engine"]["vad_speech_prob_threshold"], 0.95)
        self.assertEqual(validated["engine"]["agc_target_level"], 0.1)
        self.assertEqual(validated["engine"]["max_gain"], 100.0)

    def test_corrupted_sub_blocks_generate_warnings(self):
        corrupted = {
            "hotkeys": "invalid_string_instead_of_dict",
            "llm": 12345
        }
        is_valid, validated, warnings = ConfigSchema.validate(corrupted)
        self.assertFalse(is_valid)
        self.assertGreater(len(warnings), 0)
        self.assertIn("push_to_talk", validated["hotkeys"])

if __name__ == "__main__":
    unittest.main()
