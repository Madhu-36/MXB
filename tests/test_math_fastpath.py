import unittest
from utils.math_evaluator import SafeMathEvaluator

class TestMathFastpath(unittest.TestCase):

    def test_basic_arithmetic(self):
        self.assertEqual(SafeMathEvaluator.evaluate("10 + 20"), 30)
        self.assertEqual(SafeMathEvaluator.evaluate("50 - 15"), 35)
        self.assertEqual(SafeMathEvaluator.evaluate("8 * 9"), 72)
        self.assertEqual(SafeMathEvaluator.evaluate("100 / 4"), 25.0)

    def test_natural_phrasings(self):
        res1 = SafeMathEvaluator.try_solve("what is 25 times 4")
        self.assertIn("100", res1)

        res2 = SafeMathEvaluator.try_solve("calculate 15 percent of 200")
        self.assertIn("30", res2)

        res3 = SafeMathEvaluator.try_solve("how much is 2 to the power of 8")
        self.assertIn("256", res3)

        res4 = SafeMathEvaluator.try_solve("compute 12 squared")
        self.assertIn("144", res4)

    def test_zero_division_safety(self):
        res = SafeMathEvaluator.try_solve("what is 100 divided by 0")
        self.assertIn("division by zero", res.lower())

    def test_injection_security(self):
        # Malicious code strings must not evaluate and return None
        res1 = SafeMathEvaluator.try_solve("__import__('os').system('dir')")
        self.assertIsNone(res1)

        res2 = SafeMathEvaluator.try_solve("eval('1+1')")
        self.assertIsNone(res2)

        res3 = SafeMathEvaluator.evaluate("__import__('sys').exit()")
        self.assertIsNone(res3)

    def test_non_math_queries_return_none(self):
        self.assertIsNone(SafeMathEvaluator.try_solve("open google chrome"))
        self.assertIsNone(SafeMathEvaluator.try_solve("what is your name"))
        self.assertIsNone(SafeMathEvaluator.try_solve("mute audio"))

if __name__ == "__main__":
    unittest.main()
