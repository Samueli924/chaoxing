# -*- coding: utf-8 -*-
"""测试包入口：先隔离数据目录，任何测试都不得碰真实 ~/.chaoxing/。

注意：这里用直接赋值而不是 setdefault——单跑某个测试文件、乱序跑或 CI 并行跑时，
都不能继承真实 HOME。
"""
import os
import tempfile

os.environ["CX_DATA_HOME"] = tempfile.mkdtemp(prefix="cx-test-")
