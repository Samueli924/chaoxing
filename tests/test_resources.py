import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from api import cxsecret_font
from api.cxsecret_font import FontHashDAO

class ResourceTest(unittest.TestCase):
    def test_font_mapping_loads_outside_repository(self):
        previous = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.chdir(directory)
                FontHashDAO()
        finally:
            os.chdir(previous)

    def test_user_installation_resources_load_outside_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "user/share/chaoxing"
            data.mkdir(parents=True)
            (data / "font_map_table.json").write_text('{"example": "synthetic-hash"}')
            with mock.patch.object(cxsecret_font, "__file__", str(root / "site/api/module.py")), mock.patch.object(cxsecret_font.sys, "prefix", str(root / "prefix")), mock.patch.object(cxsecret_font.site, "getuserbase", return_value=str(root / "user")):
                dao = FontHashDAO()
                self.assertEqual(dao.find_char("synthetic-hash"), "example")
