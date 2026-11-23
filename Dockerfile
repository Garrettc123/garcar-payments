FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY backend/ ./backend/
COPY mesh_heartbeat.py ./mesh_heartbeat.py

RUN mkdir -p contracts/signed logs

CMD ["sh", "-c", "python -m app.supervisor"]
