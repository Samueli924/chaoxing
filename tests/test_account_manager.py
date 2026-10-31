import os
import shutil
import unittest
from api.account_manager import AccountManager


class TestAccountManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.join("tests", "test_accounts")
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        self.manager = AccountManager(accounts_dir=self.test_dir)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_save_and_list_accounts(self):
        saved_file = self.manager.save_account("13800000000", {
            "cookies": "_uid=12345;UID=12345;vc3=abc",
            "use_cookies": "true",
            "course_list": "111,222",
        })
        self.assertTrue(os.path.exists(saved_file))
        accounts = self.manager.list_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["username"], "13800000000")
        active = self.manager.switch_account(accounts[0]["id"])
        self.assertEqual(active["cookies"], "_uid=12345;UID=12345;vc3=abc")

    def test_auto_create_accounts_dir(self):
        custom_dir = os.path.join("tests", "test_nested_accounts")
        if os.path.exists(custom_dir):
            shutil.rmtree(custom_dir)
        AccountManager(accounts_dir=custom_dir)
        self.assertTrue(os.path.exists(custom_dir))
        shutil.rmtree(custom_dir)

    def test_daily_watch_tracking(self):
        self.assertEqual(self.manager.get_daily_watched_seconds("user1"), 0.0)
        total = self.manager.add_daily_watched_seconds("user1", 120.5)
        self.assertEqual(total, 120.5)
        self.assertEqual(self.manager.get_daily_watched_seconds("user1"), 120.5)
        total2 = self.manager.add_daily_watched_seconds("user1", 30.0)
        self.assertEqual(total2, 150.5)
        self.assertEqual(self.manager.get_daily_watched_seconds("user1"), 150.5)
        self.assertEqual(self.manager.get_daily_watched_seconds("user2"), 0.0)

    def test_merge_qr_and_password_login(self):
        self.manager.save_account("qr_session_1", {
            "cookies": "_uid=998877;UID=998877;vc3=test",
            "use_cookies": "true",
        })
        accounts = self.manager.list_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["id"], "998877")

        self.manager.save_account("13900000000", {
            "uid": "998877",
            "username": "13900000000",
            "password": "mypassword",
            "cookies": "_uid=998877;UID=998877;vc3=updated",
            "use_cookies": "true",
        })
        accounts2 = self.manager.list_accounts()
        self.assertEqual(len(accounts2), 1)
        self.assertEqual(accounts2[0]["id"], "998877")
        self.assertEqual(accounts2[0]["username"], "13900000000")

        active = self.manager.get_active_account()
        self.assertEqual(active["password"], "mypassword")
        self.assertEqual(active["cookies"], "_uid=998877;UID=998877;vc3=updated")

    def test_delete_account(self):
        self.manager.save_account("user1", {"cookies": "UID=111"})
        self.manager.save_account("user2", {"cookies": "UID=222"})
        self.assertEqual(len(self.manager.list_accounts()), 2)

        ok = self.manager.delete_account("111")
        self.assertTrue(ok)
        accounts = self.manager.list_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["id"], "222")

        fail = self.manager.delete_account("non_exist")
        self.assertFalse(fail)

    def test_empty_username_in_ini_falls_back_to_uid(self):
        self.manager.save_account("887766", {
            "uid": "887766",
            "username": "",
            "cookies": "_uid=887766;UID=887766",
        })
        accounts = self.manager.list_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["username"], "887766")
        active = self.manager.get_active_account()
        self.assertEqual(active["username"], "887766")
