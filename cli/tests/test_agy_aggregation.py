import unittest
from kanjo.subscriptions import _aggregate_antigravity_accounts

class TestAntigravityAggregation(unittest.TestCase):
    def test_none_handling(self):
        accounts = {
            "a@test.com": {"plan": "google_ai_pro"},
            "b@test.com": {"plan": "none"},
            "c@test.com": {"plan": "google_ai_pro"},
        }
        result = _aggregate_antigravity_accounts(accounts)
        self.assertEqual(result["accounts_priced"], 2)
        self.assertEqual(result["monthly_price_usd"], 39.98)
        self.assertIn("×2", result["plan_label"])

if __name__ == '__main__':
    unittest.main()
