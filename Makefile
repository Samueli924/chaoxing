# 常用命令：给人和 Agent 共用
PY ?= python3
.PHONY: help test lint compile publication doctor

help:  ## 列出所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# 本地默认解释器可能比 CI 新（如 3.14）：注解求值时机不同，
# 提交前用 CI 同版本再跑一遍，避免"本地绿、CI 红"。
#   make test-313                          # 系统 python3.13（没装依赖就跳过）
#   make test-313 PY313=/tmp/cx313/bin/python   # 自己建好的 3.13 venv
PY313 ?= python3.13

test-313:
	@if ! command -v $(PY313) >/dev/null 2>&1 && [ ! -x "$(PY313)" ]; then \
		echo "没有 $(PY313)，跳过（CI 会跑）"; \
	elif ! $(PY313) -c "import loguru, openai, bs4, lxml, requests, httpx, tqdm, tenacity" 2>/dev/null; then \
		echo "$(PY313) 缺依赖，跳过（CI 会跑）。本地对齐：python3.13 -m venv /tmp/cx313 && /tmp/cx313/bin/pip install -r requirements.txt"; \
	else \
		$(PY313) -m compileall -q api main.py setup_wizard.py tools tests && \
		$(PY313) -m unittest discover -s tests -t .; \
	fi

test:  ## 跑全量单测（离线）
	$(PY) -m unittest discover -s tests -t .

compile:  ## 语法编译检查
	$(PY) -m compileall -q api main.py tools tests

publication:
	$(PY) tools/audit/publication_guard.py

lint: publication compile test  ## 提交前必跑：编译 + 单测

doctor:  ## 环境自检
	@echo "python : $$($(PY) -V)"
	@echo "venv   : $$(test -x $(PY) && echo ok || echo missing)"
	@echo "data   : $$(test -d $$HOME/.chaoxing && echo $$HOME/.chaoxing || echo 'missing (~/.chaoxing)')"
	@$(PY) -c "import requests, bs4, loguru, tqdm; print('deps   : ok')"
