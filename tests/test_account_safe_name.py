import unittest

from api.account_manager import AccountManager


class TestSafeName(unittest.TestCase):
    def test_keeps_digits_and_hyphen(self):
        self.assertEqual(AccountManager._safe_name("419769884"), "419769884")
        self.assertEqual(AccountManager._safe_name("a-b_c1"), "a-b_c1")

    def test_strips_path_separators(self):
        self.assertEqual(AccountManager._safe_name("../etc/passwd"), "etcpasswd")

    def test_uses_default_when_empty(self):
        self.assertEqual(AccountManager._safe_name("", "default"), "default")
        self.assertEqual(AccountManager._safe_name("", ""), "")


if __name__ == "__main__":
    unittest.main()
