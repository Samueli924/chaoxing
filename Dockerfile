FROM python:3.9-alpine as builder
RUN apk update && apk add gcc musl-dev linux-headers
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
RUN pip install pyinstaller==5.9.0
RUN pyinstaller -F main.py -n chaoxing

FROM alpine:3.17
COPY --from=builder /app/dist /app
WORKDIR /app
CMD ["./chaoxing"]
