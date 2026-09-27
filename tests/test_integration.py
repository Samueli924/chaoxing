import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from api.question_bank import QuestionBank
from api.runtime import Runtime
from api.settings import normalize_common
from api.web import WebApp
from api.answer import Tiku, TikuLocal
from scripts.local import load_env

class BankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bank = QuestionBank(Path(self.tmp.name)/"bank.sqlite3")

    def test_import_update_delete_and_pagination(self):
        row = {"question": "1 示例（2分）", "type": "single", "options": ["A. 甲", "B. 乙"], "answer": "甲"}
        self.bank.import_rows([row])
        self.assertEqual(self.bank.search("示例", "single", row["options"]), "甲")
        self.assertIsNone(self.bank.search("示例", "single", list(reversed(row["options"]))))
        self.bank.import_rows([dict(row, answer="乙")])
        page = self.bank.list_rows()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["rows"][0]["answer"], "乙")
        self.assertEqual(self.bank.list_rows(offset=1)["rows"], [])
        self.assertTrue(self.bank.delete(page["rows"][0]["id"]))
        self.assertIsNone(self.bank.search("示例", "single", row["options"]))

    def test_batch_validation_is_atomic(self):
        with self.assertRaises(ValueError):
            self.bank.import_rows([{"question":"valid", "answer":"yes"}, {"question":"invalid"}])
        self.assertEqual(self.bank.list_rows()["total"], 0)

    def test_type_is_part_of_key_and_sql_is_parameterized(self):
        self.bank.import_rows([{"question":"x' OR 1=1 --", "answer":"正确", "type":"3"}])
        self.assertIsNone(self.bank.search("x", "3"))
        self.assertIsNone(self.bank.search("x' OR 1=1 --", "0"))
        self.assertEqual(self.bank.search("x' OR 1=1 --", "3"), "正确")

    def test_local_provider_sees_updates_without_cache(self):
        tiku = TikuLocal(); tiku.config_set({"provider":"TikuLocal"}); tiku.init_tiku()
        with patch("api.question_bank.QuestionBank", return_value=self.bank):
            self.bank.import_rows([{"question":"example", "answer":"甲"}])
            self.assertEqual(tiku.query({"title":"example","type":"single"}), "甲")
            self.bank.import_rows([{"question":"example", "answer":"乙"}])
            self.assertEqual(tiku.query({"title":"example","type":"single"}), "乙")

    def test_chain_uses_local_before_remote(self):
        chain = Tiku.get_tiku_from_config({"provider":"TikuLocal,TikuCustom", "custom_url":"https://example.invalid/api/search"}); chain.init_tiku()
        self.bank.import_rows([{"question":"example", "answer":"甲"}])
        with patch("api.question_bank.QuestionBank", return_value=self.bank), patch("requests.post") as post:
            self.assertEqual(chain.query({"title":"example","type":"single","options":"A. 甲\nB. 乙"}), "甲")
            post.assert_not_called()

class ConfigTests(unittest.TestCase):
    def test_chain_keeps_order_deduplicates_and_rejects_unknown(self):
        self.assertEqual(WebApp._tiku_overrides({"provider_chain":"TikuLocal,AI,TikuLocal"})["provider"], "TikuLocal,AI")
        with self.assertRaises(ValueError): WebApp._tiku_overrides({"provider_chain":"TikuLocal,missing"})

    def test_nonfinite_and_limits(self):
        self.assertEqual(normalize_common({"max_duration": -3})["max_duration"],0)
        self.assertEqual(normalize_common({"max_duration": 100000})["max_duration"],86400)
        self.assertEqual(normalize_common({"speed":"nan"})["speed"],1)
        self.assertEqual(normalize_common({"jobs":"inf"})["jobs"],4)

    def test_env_is_literal_and_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.env"
            path.write_text("OTHER_SECRET=ignored\nexport CHAOXING_USERNAME='test'\nCHAOXING_PASSWORD=\"a$()#% b\"\nCHAOXING_JOBS=2 # note\n")
            self.assertEqual(load_env(path),{"CHAOXING_USERNAME":"test","CHAOXING_PASSWORD":"a$()#% b","CHAOXING_JOBS":"2"})

class RuntimeTests(unittest.TestCase):
    def test_deadline_expires_and_reset_clears_it(self):
        runtime=Runtime()
        with patch("api.runtime.time.monotonic", return_value=100):
            runtime.set_time_limit(5); self.assertFalse(runtime.should_stop())
        with patch("api.runtime.time.monotonic", return_value=105):
            self.assertTrue(runtime.sleep(30)); self.assertEqual(runtime.stop_reason,"time_limit")
        runtime.reset(); self.assertFalse(runtime.should_stop()); self.assertIsNone(runtime.deadline)

    def test_stop_interrupts_sleep(self):
        runtime=Runtime();runtime.request_stop();self.assertTrue(runtime.sleep(100))

    def test_unlimited_run(self):
        runtime=Runtime();runtime.set_time_limit(0);self.assertIsNone(runtime.deadline)

class BatchTests(unittest.TestCase):
    def test_profiles_reject_duplicates_and_unbounded_run(self):
        import json
        from scripts.batch import prepare_profiles
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"profiles.json";env=Path(tmp)/"test.env";env.write_text("")
            row={"name":"test","env_file":"test.env","courses":["1"]}
            path.write_text(json.dumps([row,row]))
            with self.assertRaises(ValueError):prepare_profiles(path)
            path.write_text(json.dumps([dict(row,courses=[])]))
            with self.assertRaises(ValueError):prepare_profiles(path,run=True)
            path.write_text(json.dumps([row]))
            self.assertEqual(prepare_profiles(path)[0]["name"],"test")

    def test_profile_environment_does_not_inherit_other_account(self):
        from scripts.batch import profile_environment
        with patch.dict("os.environ",{"CHAOXING_USERNAME":"other","CHAOXING_PASSWORD":"other","CHAOXING_TIKU_KEY":"other"}):
            env=profile_environment(Path("/test/profile"))
        self.assertNotIn("CHAOXING_USERNAME",env)
        self.assertNotIn("CHAOXING_TIKU_KEY",env)
        self.assertEqual(env["CHAOXING_DATA_DIR"],"/test/profile")
        self.assertEqual(env["CHAOXING_NOTIFICATION_PROVIDER"],"")

class BankHttpTests(unittest.TestCase):
    def setUp(self):
        import threading
        from api.web import create_server
        from api.settings import Settings, COMMON_DEFAULTS
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        bank=QuestionBank(Path(self.tmp.name)/"bank.sqlite3")
        patcher=patch("api.web.QuestionBank",return_value=bank);patcher.start();self.addCleanup(patcher.stop)
        self.server=create_server(Settings(dict(COMMON_DEFAULTS)),"127.0.0.1",0,"test-access")
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def call(self,path,body=None,authorized=True):
        import json
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        headers={"Content-Type":"application/json","X-Requested-With":"chaoxing-web"}
        if authorized: headers["X-Token"]="test-access"
        req=Request(f"http://127.0.0.1:{self.server.server_port}"+path,headers=headers,data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(req) as res:return res.status,json.load(res)
        except HTTPError as exc:return exc.code,json.load(exc)

    def test_import_search_readback_delete(self):
        row={"question":"fixture","answer":"甲"}
        self.assertEqual(self.call("/api/bank/import",{"rows":[row]})[1]["count"],1)
        self.assertEqual(self.call("/api/search",{"question":"fixture"})[1]["data"]["answer"],"甲")
        rows=self.call("/api/bank")[1]["rows"]
        self.assertTrue(self.call("/api/bank/delete",{"id":rows[0]["id"]})[1]["ok"])
        self.assertEqual(self.call("/api/bank")[1]["total"],0)

    def test_invalid_import_rejected_without_partial_write(self):
        status,_=self.call("/api/bank/import",{"rows":[{"question":"fixture","answer":"甲"},{"question":"invalid"}]})
        self.assertEqual(status,400)
        self.assertEqual(self.call("/api/bank")[1]["total"],0)

    def test_bank_and_search_require_access_token(self):
        self.assertEqual(self.call("/api/bank",authorized=False)[0],401)
        self.assertEqual(self.call("/api/search",{"question":"fixture"},authorized=False)[0],401)
