FROM python:3.9-alpine as builder
RUN apk update && apk add gcc musl-dev linux-headers
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
RUN pip install pyinstaller
RUN pyinstaller -F main.py -n chaoxing

FROM alpine
COPY --from=builder /app/dist /app
WORKDIR /app
CMD ["./chaoxing"]
