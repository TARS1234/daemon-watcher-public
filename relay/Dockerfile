# Build from project root:  docker build -f relay/Dockerfile .
FROM python:3.11-slim

WORKDIR /app
COPY relay/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY relay_server.py .

ENV PORT=8000
EXPOSE $PORT

CMD ["sh", "-c", "python3 relay_server.py --host 0.0.0.0 --port $PORT"]
