FROM python:3.11.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CMAKE_ARGS="-DGGML_NATIVE=OFF" FORCE_CMAKE=1
WORKDIR /app
ARG WITH_LLM=0
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN if [ "$WITH_LLM" = "1" ]; then \
			apt-get update && apt-get install -y --no-install-recommends build-essential cmake git && \
			pip install --no-cache-dir -r requirements.txt && \
			rm -rf /var/lib/apt/lists/*; \
		fi
COPY engine.py intents.py sql_templates.py analytics.py rootcause.py llm.py grammar.gbnf ./
RUN useradd --uid 10002 --create-home engineuser && mkdir -p /data /ipc && chown engineuser:engineuser /ipc
USER 10002:10002
CMD ["python", "engine.py"]