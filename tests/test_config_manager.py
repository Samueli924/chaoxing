import os
import unittest
from api.config_manager import ConfigManager


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.test_ini = os.path.join("tests", "test_account_conf.ini")
        with open(self.test_ini, "w", encoding="utf8") as f:
            f.write(
                "[common]\n"
                "course_list = 111,222\n"
                "speed = 1.0\n"
                "jobs = 4\n"
                "[tiku]\n"
                "provider = TikuYanxi\n"
                "[notification]\n"
                "provider = ServerChan\n"
            )
        self.cfg = ConfigManager(config_path=self.test_ini)

    def tearDown(self):
        if os.path.exists(self.test_ini):
            os.remove(self.test_ini)

    def test_course_list(self):
        self.assertEqual(self.cfg.get_course_list(), ["111", "222"])
        self.cfg.set_course_list(["333", "444"])
        self.assertEqual(self.cfg.get_course_list(), ["333", "444"])

    def test_full_config_lifecycle(self):
        full_cfg = self.cfg.get_full_config()
        self.assertIn("common", full_cfg)
        self.assertIn("tiku", full_cfg)
        self.assertIn("notification", full_cfg)
        self.assertEqual(full_cfg["common"]["jobs"], 4)

        full_cfg["common"]["jobs"] = 8
        full_cfg["tiku"]["provider"] = "TikuManual"
        full_cfg["notification"]["tg_chat_id"] = "12345678"

        self.cfg.update_full_config(full_cfg)
        updated = self.cfg.get_full_config()
        self.assertEqual(updated["common"]["jobs"], 8)
        self.assertEqual(updated["tiku"]["provider"], "TikuManual")
        self.assertEqual(updated["notification"]["tg_chat_id"], "12345678")

    def test_template_placeholders_sanitized(self):
        full_cfg = self.cfg.get_full_config()
        self.assertEqual(full_cfg["common"].get("username"), "")
        self.assertEqual(full_cfg["common"].get("password"), "")
        self.assertEqual(full_cfg["notification"].get("tg_chat_id"), "")

    def test_auto_provision_from_template(self):
        missing_ini = os.path.join("tests", "test_auto_provision.ini")
        if os.path.exists(missing_ini):
            os.remove(missing_ini)
        ConfigManager(config_path=missing_ini, template_path="config_template.ini")
        self.assertTrue(os.path.exists(missing_ini))
        os.remove(missing_ini)
