import os
import unittest


class TestFrontendAssets(unittest.TestCase):
    def test_frontend_files_exist(self):
        paths = [
            os.path.join("web", "templates", "index.html"),
            os.path.join("web", "static", "css", "style.css"),
            os.path.join("web", "static", "js", "api.js"),
            os.path.join("web", "static", "js", "app.js"),
        ]
        for p in paths:
            self.assertTrue(os.path.exists(p), f"缺少必要前端文件: {p}")

    def test_html_contains_required_modals(self):
        html_path = os.path.join("web", "templates", "index.html")
        if not os.path.exists(html_path):
            self.fail("index.html 不存在")
        with open(html_path, "r", encoding="utf8") as f:
            content = f.read()
        self.assertIn("settingsModalOverlay", content)
        self.assertIn("manualQuizModalOverlay", content)
        self.assertIn("loginModalOverlay", content)
        self.assertIn("btnScrollBottom", content)

    def test_js_contains_scroll_pinning(self):
        js_path = os.path.join("web", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf8") as f:
            content = f.read()
        self.assertIn("isLogPinnedToBottom", content)
        self.assertIn("scrollToLogBottom", content)
