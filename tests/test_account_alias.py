import configparser
import os
import tempfile
import unittest

from api.account_manager import AccountManager


class TestAccountAlias(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mgr = AccountManager(accounts_dir=self.tmp.name, auto_import_legacy=False)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, acc_id: str, username: str, alias: str = "") -> None:
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.add_section("common")
        cfg.set("common", "uid", acc_id)
        cfg.set("common", "username", username)
        if alias:
            cfg.set("common", "alias", alias)
        with open(os.path.join(self.tmp.name, f"{acc_id}.ini"), "w", encoding="utf8") as f:
            cfg.write(f)

    def test_display_name_prefers_alias(self):
        self._write("419769884", "13657277490", "小号")
        accounts = self.mgr.list_accounts()
        self.assertEqual(accounts[0]["display_name"], "小号")
        self.assertEqual(accounts[0]["alias"], "小号")

    def test_display_name_falls_back_to_uid(self):
        self._write("419769884", "13657277490")
        accounts = self.mgr.list_accounts()
        self.assertEqual(accounts[0]["display_name"], "419769884")
        self.assertEqual(accounts[0]["alias"], "")

    def test_set_alias_persists(self):
        self._write("419769884", "13657277490")
        self.assertTrue(self.mgr.set_alias("419769884", "小号"))

        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(os.path.join(self.tmp.name, "419769884.ini"), encoding="utf8")
        self.assertEqual(cfg.get("common", "alias"), "小号")
        self.assertEqual(self.mgr.list_accounts()[0]["display_name"], "小号")

    def test_blank_alias_restores_uid(self):
        self._write("419769884", "13657277490", "小号")
        self.assertTrue(self.mgr.set_alias("419769884", "   "))

        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(os.path.join(self.tmp.name, "419769884.ini"), encoding="utf8")
        self.assertFalse(cfg.has_option("common", "alias"))
        self.assertEqual(self.mgr.list_accounts()[0]["display_name"], "419769884")

    def test_set_alias_rejects_unknown_account(self):
        self.assertFalse(self.mgr.set_alias("nope", "小号"))


if __name__ == "__main__":
    unittest.main()
