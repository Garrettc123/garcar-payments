# Garcar Payments staging-only signed telemetry canary.
# Excludes payment supervisor, checkout, Stripe, webhooks, refunds, and fulfillment.
FROM python:3.11-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY mesh_heartbeat.py /app/mesh_heartbeat.py
USER 65532:65532
CMD ["sh", "-c", "while true; do python -u /app/mesh_heartbeat.py; sleep 300; done"]
