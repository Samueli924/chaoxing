import os
import unittest

from api.logger import (
    CLI_LOG_DIR,
    CLI_LOG_FILE,
    GUI_LOG_DIR,
    GUI_LOG_FILE,
    logger,
    setup_cli_logging,
    setup_webui_logging,
)


class TestLoggerConfig(unittest.TestCase):
    def test_log_directories_exist(self):
        self.assertTrue(os.path.isdir(CLI_LOG_DIR))
        self.assertTrue(os.path.isdir(GUI_LOG_DIR))

    def test_webui_logging(self):
        setup_webui_logging()
        logger.info("webui test message")
        self.assertTrue(os.path.exists(GUI_LOG_FILE))
        with open(GUI_LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("webui test message", content)

    def test_cli_logging(self):
        setup_cli_logging()
        logger.info("cli test message")
        self.assertTrue(os.path.exists(CLI_LOG_FILE))
        with open(CLI_LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("cli test message", content)
