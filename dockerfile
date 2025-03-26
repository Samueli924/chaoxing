# 使用官方 Python 运行时作为父镜像
FROM python:3.12-slim

# 设置工作目录
VOLUME /app
WORKDIR /app
# 将当前目录内容复制到位于 /usr/src/app 的工作目录下
COPY requirements.txt .

# 安装 requirements.txt 中指定的任何所需包
RUN pip install --no-cache-dir -r requirements.txt

# 解决 docker 时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 定义环境变量
ENV NAME World

# 运行 app.py 当容器启动时
CMD ["python","-u", "main.py", "-c", "config.ini"]
