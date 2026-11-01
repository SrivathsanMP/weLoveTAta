FROM python:3.11.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ingest.py simulator.py adapters.py signals.dbc ./
RUN groupadd --gid 10000 vehiclegpt-data && useradd --uid 10001 --gid 10000 --create-home appuser && mkdir -p /data && chown appuser:vehiclegpt-data /data
USER 10001:10000
CMD ["python", "ingest.py"]