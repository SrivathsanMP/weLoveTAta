# VehicleGPT 🚗
### Offline Vehicle Intelligence with Deterministic Analytics

VehicleGPT is an offline, read-only vehicle-history assistant that analyzes vehicle telemetry, detects anomalies, reconstructs events, and answers vehicle-related questions using deterministic SQL and analytics.

Unlike conventional AI assistants, VehicleGPT uses an optional small language model only for intent extraction. All numerical results and analytical answers come directly from SQL and deterministic computations, ensuring predictable and verifiable outputs.

## Key Features

- **Offline-first:** Runs locally without runtime internet access or cloud AI dependencies.
- **Deterministic Analytics:** SQL and rule-based functions calculate every result.
- **Vehicle Anomaly Detection:** Identifies unusual telemetry patterns.
- **Event Reconstruction:** Reconstructs events such as engine overheating from historical signals.
- **Historical Analysis:** Evaluates range loss, fuel efficiency changes, ADAS activity, and tyre-pressure anomalies.
- **Optional Local LLM:** Supports GGUF-based intent extraction with deterministic fallback.
- **Read-only Engine:** Prevents analytical queries from modifying vehicle records.

## Architecture

VehicleGPT uses three isolated services:

- **UI:** FastAPI-based local browser interface.
- **Engine:** Intent routing, SQL execution, and deterministic analytics.
- **Ingest:** Synthetic telemetry or SocketCAN data ingestion.

The UI and engine communicate through a private Unix domain socket. The engine has no network connectivity and accesses SQLite in read-only mode.

## Technology Stack

Python 3.11 · FastAPI · SQLite · Docker Compose · llama.cpp · GGUF · Python-can · cantools · SocketCAN

## Quick Start

**Prerequisites:** Docker Desktop with Compose v2 and Python 3.11+.

```bash
docker compose build
docker compose up -d
python tests/test_queries.py
```

Open the application:

http://127.0.0.1:8080

## Testing

Automated tests validate five primary scenarios against generated ground-truth data:

1. Vehicle range loss
2. Engine overheating event and temperature ramp
3. Previous day's ADAS event count
4. Fuel-efficiency change point
5. Tyre-pressure anomaly

Tests report PASS/FAIL results and median/p95 engine latency.

## Security & Privacy

- No application data or model downloads at runtime.
- Engine network namespace disabled.
- SQLite read-only access with `PRAGMA query_only=ON`.
- Container capability restrictions and non-root execution.
- Separate ingestion and analytical services.

These controls demonstrate prototype-level isolation, not production-grade automotive security.

## Limitations

- Uses synthetic telemetry and demonstration signal definitions.
- Root-cause contributions are heuristic scores, not validated causal estimates.
- SocketCAN requires a configured Linux host interface.
- Not safety-certified or validated on production vehicle hardware.

**VehicleGPT is an engineering prototype and must not control the vehicle.**

---

### Project Goal

To demonstrate how offline AI-assisted interaction can work alongside deterministic analytics, local data processing, and transparent security boundaries.

**VehicleGPT — Local Intelligence. Deterministic Answers. Privacy by Design.**
