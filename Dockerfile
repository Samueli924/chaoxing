FROM python:3.13-slim

WORKDIR /app

# 依赖单独一层，改代码不用重装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY api ./api
COPY resource ./resource
COPY tools ./tools
COPY main.py setup_wizard.py config_template.ini Makefile ./

# 账号 / 配置 / cookie / 日志都落在 /root/.chaoxing，挂载出来才能持久化
VOLUME ["/root/.chaoxing"]

# 默认进入交互式向导（docker run -it）；也可以覆盖命令跑 main.py
ENTRYPOINT ["python3", "setup_wizard.py"]
