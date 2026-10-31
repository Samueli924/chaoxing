FROM python:3.13-slim

WORKDIR /app

ENV HOST=0.0.0.0

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . /app

RUN mkdir -p /config /app/accounts /app/logs && \
    cp config_template.ini /config/config.ini

EXPOSE 5000

VOLUME ["/config", "/app/accounts", "/app/logs"]

ENTRYPOINT ["python3", "main.py"]
CMD ["-c", "/config/config.ini"]
