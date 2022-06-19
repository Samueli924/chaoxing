FROM python:3.9
COPY . /
WORKDIR /
RUN pip install -r requirements.txt
ENTRYPOINT ["python3","/main.py"]