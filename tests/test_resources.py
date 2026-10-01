import os
import tempfile
import unittest
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
