"""Local SQLite question bank. Stores user-curated questions, never account credentials."""
import json
import sqlite3
import re
from contextlib import contextmanager
from pathlib import Path
from api.config import data_path

TYPES = {"single": "0", "multiple": "1", "completion": "2", "judgement": "3", "shortanswer": "4"}


def clean_question(text):
    text = re.sub(r'^\d+', '', str(text or ''))
    return re.sub(r'[（(]\s*\d+(\.\d+)?\s*分\s*[）)]\s*$', '', text).strip()


def normalize(row):
    if not isinstance(row, dict):
        raise ValueError("每条题目必须是对象")
    if not isinstance(row.get("question"), str) or not isinstance(row.get("answer"), str):
        raise ValueError("题目和答案必须是字符串")
    question = clean_question(row.get("question", ""))
    answer = str(row.get("answer", "")).strip()
    kind = str(row.get("type", "0"))
    kind = TYPES.get(kind, kind)
    options = row.get("options", [])
    if isinstance(options, str):
        options = options.splitlines()
    if not isinstance(options, list) or not all(isinstance(x, str) for x in options):
        raise ValueError("options 必须是字符串数组")
    if not question or not answer or kind not in {str(i) for i in range(8)}:
        raise ValueError("题目、答案不可为空；题型须为 0–7")
    if len(question) > 10000 or len(answer) > 20000 or len(json.dumps(options)) > 20000:
        raise ValueError("题目内容过长")
    return question, kind, json.dumps([x.strip() for x in options], ensure_ascii=False), answer


class QuestionBank:
    def __init__(self, path=None):
        self.path = Path(path or data_path("question_bank.sqlite3"))

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, question TEXT NOT NULL, type TEXT NOT NULL, options TEXT NOT NULL, answer TEXT NOT NULL, UNIQUE(question,type,options))")
        self.path.chmod(0o600)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def import_rows(self, rows):
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError("每次导入须为最多 500 条题目的 JSON 数组")
        values = [normalize(row) for row in rows]  # validate entire batch before writing
        with self.connect() as db:
            db.executemany("INSERT INTO questions(question,type,options,answer) VALUES (?,?,?,?) ON CONFLICT(question,type,options) DO UPDATE SET answer=excluded.answer", values)
        return len(values)

    def list_rows(self, query="", limit=100, offset=0):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM questions WHERE instr(question,?)>0 ORDER BY id DESC LIMIT ? OFFSET ?", (str(query), min(500, max(1, int(limit))), max(0, int(offset)))).fetchall()
            total = db.execute("SELECT COUNT(*) FROM questions WHERE instr(question,?)>0", (str(query),)).fetchone()[0]
        return {"rows": [dict(row, options=json.loads(row["options"])) for row in rows], "total": total}

    def delete(self, row_id):
        with self.connect() as db:
            return db.execute("DELETE FROM questions WHERE id=?", (int(row_id),)).rowcount > 0

    def search(self, question, kind="0", options=None):
        # An empty-options entry explicitly represents an answer independent of option order.
        kind = TYPES.get(str(kind), str(kind))
        if isinstance(options, str):
            options = options.splitlines()
        encoded = json.dumps([str(x).strip() for x in (options or [])], ensure_ascii=False)
        with self.connect() as db:
            row = db.execute("SELECT answer FROM questions WHERE question=? AND type=? AND options IN (?, '[]') ORDER BY CASE WHEN options=? THEN 0 ELSE 1 END LIMIT 1", (clean_question(question), kind, encoded, encoded)).fetchone()
        return row[0] if row else None
