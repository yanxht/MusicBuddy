FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY musicbuddy ./musicbuddy

RUN useradd --create-home app && mkdir -p /app/work && chown app /app/work
USER app

ENV PYTHONUNBUFFERED=1 PORT=8000 MB_RUN_WORKER=1 MB_WORK_DIR=/app/work
EXPOSE 8000
CMD ["sh", "-c", "uvicorn musicbuddy.web.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
