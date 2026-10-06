FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/output /app/logs \
    && chown -R app:app /app

COPY --chown=app:app . .

USER app
VOLUME ["/app/output", "/app/logs"]
ENTRYPOINT ["python", "main.py"]
