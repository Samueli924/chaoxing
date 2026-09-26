FROM python:3.13-slim

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# 数据目录（cookies / 缓存 / 日志），可挂载持久化
ENV CHAOXING_DATA_DIR=/data
VOLUME /data
RUN mkdir -p /data

# 网页控制台默认监听 8765
EXPOSE 8765
ENV CHAOXING_WEB_HOST=0.0.0.0 \
    CHAOXING_WEB_PORT=8765

# 默认启动网页控制台（对外开放时会自动生成访问口令并打印到日志；
# 也可用 docker run ... chaoxing -u 手机号 -p 密码 切换为命令行模式）
ENTRYPOINT ["python", "main.py"]
CMD ["--web", "--no-browser"]
