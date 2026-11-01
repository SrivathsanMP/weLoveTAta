# VehicleGPT

VehicleGPT is an offline, read-only vehicle-history assistant prototype. SQL and deterministic analytics calculate every fact and number. The optional small language model extracts intent only; it does not write SQL or author numerical answers.

## Architecture

```text
                         loopback only
 Browser ─────────────── 127.0.0.1:8080
                              │ HTTP
                         ┌────▼────┐
                         │   ui    │  FastAPI, static offline page
                         └────┬────┘
                              │ Unix socket in ipc volume
                     ┌────────▼────────┐        /models (read-only)
                     │     engine      │◄──────── local GGUF (optional)
                     │ network: none   │
                     └────────┬────────┘
                              │ SQLite URI mode=ro + query_only
  ┌───────────────────────────▼───────────────────────────┐
  │ /data/vehicle.db                                      │
  │ signals · events · 1-minute/hour aggregates · event FTS│
  └───────────────────────────▲───────────────────────────┘
                              │ only writer
                         ┌────┴────┐
                         │ ingest  │ SIM or SocketCAN
                         └─────────┘
```

The engine/UI exchange newline-delimited JSON over `/ipc/engine.sock`; neither has a TCP service between them. The browser only reaches the UI's loopback-bound HTTP port.

## Assumptions

- SIM uses deterministic five-minute samples for 30 days to keep ingest memory bounded. Each sample is placed in its corresponding 1-minute bucket; hour buckets are derived from samples. The event reconstruction includes three samples across the ten-minute overheating ramp.
- SIM timestamps are generated relative to the machine's current UTC time. `ground_truth.json` is regenerated on each seed and is the reference for tests.
- The daily ADAS events mean yesterday in UTC. The efficiency transition is 18 days before the generated end time; its documented tolerance is two days.
- The demo signal set is the requested 12 signals. This is a prototype schema, not a production OEM signal dictionary.
- Engineer access is disabled unless `ENGINEER_TOKEN` is explicitly configured. The token is a local prototype stub, not production identity or authorization.
- `MOCK_LLM=1` is the default. Without a local model, supported keyword intents still work and unknown questions receive a refusal with suggested phrasings. `MOCK_LLM=0` attempts to load the named GGUF and falls back to deterministic routing if the file is absent.
- Cause contribution percentages are normalized rule scores from measured signal deltas, not causal estimates from a validated vehicle model. Low evidence produces an explicit insufficient-evidence result.

## Quick Start

Prerequisites: Docker Desktop with Compose v2, and Python 3.11+ on the host for the HTTP integration test. The container images use Python 3.11.

From the project directory:

```sh
docker compose build
docker compose up -d
python tests/test_queries.py
```

Open <http://127.0.0.1:8080>. The first build compiles `llama-cpp-python`; that dependency is used only when enabling local inference. No model or application data is downloaded at runtime. To follow the Makefile targets where `make` is installed:

```sh
make build
make up
make test
```

To enable the engineer view for a local session, set a private token in your shell before starting Compose. Do not commit the value or put it in a checked-in `.env` file:

```powershell
$env:ENGINEER_TOKEN = "choose-a-private-local-value"
docker compose up -d
```

Useful operations:

```sh
docker compose logs -f --tail=100
docker compose ps
docker compose down
```

The first SIM seed runs as the `ingest` service when Compose starts. Reseed explicitly with `docker compose run --rm --no-deps ingest`; this replaces the SIM fixture and its ground truth. The test command expects the stack to be up.

## Local GGUF

Place the Qwen2.5-0.5B-Instruct Q4_K_M model at `models/qwen2.5-0.5b-instruct-q4_k_m.gguf`. The default image skips compiling the native binding because mock mode does not need it. To build `llama-cpp-python` from source for the selected Docker architecture (amd64 or arm64), then recreate the engine with mock mode disabled:

```sh
WITH_LLM=1 docker compose build engine
MOCK_LLM=0 docker compose up -d engine
```

On PowerShell, set `$env:MOCK_LLM = "0"` before running Compose. The grammar constrains extraction to the intent/time-range/signals/filters JSON shape. The SQL allow-list is independent of model output, and answer values continue to come exclusively from SQLite and analytics.

## Isolation And Limits

| Setting | What it demonstrates | Boundary |
| --- | --- | --- |
| Engine `network_mode: none` | No engine network namespace route or outbound socket path | Does not establish a production security boundary against host/kernel compromise |
| Unix socket on a private named volume | UI/engine IPC without an engine TCP listener | The UI remains reachable on the host loopback |
| UI Host and Origin checks | Rejects non-loopback Host headers and cross-origin API requests | Helps prevent DNS rebinding and cross-origin request abuse; the local driver API is not an authentication boundary |
| SQLite `mode=ro` and `PRAGMA query_only=ON` | Assistant queries cannot mutate records through its database connection | `/data` is a Docker-managed volume so SQLite WAL and shared-memory sidecars use the Linux filesystem rather than the Windows/OneDrive bind mount; the engine's connection remains query-only. |
The first SIM seed runs as the `ingest` service when Compose starts. Reseed explicitly with `docker compose run --rm --no-deps ingest`; this replaces the SIM fixture and its ground truth in the Docker-managed `vehicle_data` volume. The HTTP test copies the matching `ground_truth.json` from the engine container into `data/` before checking results. The test command expects the stack to be up.
| `cap_drop: ALL`, read-only root filesystems, `no-new-privileges` | Removes Linux capabilities and blocks container-root filesystem writes/privilege gain | Writable data, IPC, and temporary mounts remain as configured |
| Non-root UIDs | Reduces process privilege in each container | Container users are not a substitute for host isolation |
| `mem_limit` and `cpuset` | Requests 300 MB/1 CPU for ingest, 1000 MB/2 CPUs for engine, and 200 MB for UI | Docker/OS enforcement and CPU numbering depend on the target host |
| No CAN device/interface in engine or UI | Neither consumer receives a CAN interface from Compose | Hardware access belongs only to the separate ingest service |

Run the isolation checks from a POSIX shell with Docker access:

```sh
sh tests/test_isolation.sh
```

The script checks that `ping` fails, rejects an SQL write through a read-only connection, checks network interfaces for CAN devices, inspects configured CPU/memory limits, and prints current `docker stats`.

To emulate the 2 GB / 2-core target, use a Linux host or VM with two CPUs and at least 2 GB RAM, then run `docker compose up`. The containers are capped at 1.5 GB combined; leave the remaining memory for the OS and Docker. CPU affinity assumes host CPUs `0` and `1` exist. On a host with different CPU numbering, edit the `cpuset` values to match before starting.

## Real CAN Input

On a Linux host with a configured SocketCAN interface (including vCAN), select the override so `NET_RAW` is granted only to ingest:

```sh
CAN_IFACE=vcan0 docker compose -f docker-compose.yml -f docker-compose.socketcan.yml up -d --build
```

For a physical interface, use `CAN_IFACE=can0`. The host must create/configure that interface first. Python-can and cantools decode `ingest/signals.dbc`; decoded rows use the same common signal table. The DBC and mapping are demonstration examples and must be replaced with the vehicle's approved signal definitions and unit conversions. Docker Desktop on Windows/macOS does not expose a host SocketCAN interface in the same way as native Linux; use SIM there or run the ingest adapter on a Linux target.

`ingest/adapters.py` provides common-writer interfaces and explicit TODO stubs for vsomeip/SOME-IP, Android VHAL, and QNX slog2. These are integration contracts, not working platform adapters.

## Tests And Performance

`tests/test_queries.py` sends the five primary test questions to the local UI and compares range loss, overheating timestamp/ramp, yesterday's ADAS event count, efficiency change-point date, and tyre-pressure anomaly with `data/ground_truth.json`. It prints PASS/FAIL rows plus median and p95 engine latency. The UI also includes the city/highway comparison as a sixth interactive scenario.

On a Windows host where the engine's Linux Unix-socket transport cannot run directly, use `python tests/test_queries.py --local` to run those same five assertions against the deterministic engine core and local SQLite fixture.

The sub-100 ms fast-path intent target is a **target to validate**, not a measured guarantee. All latency values shown by the app/tests are measurements from the current host and workload; they are not claims about an automotive target ECU.

## Known Limitations

| Area | Limitation |
| --- | --- |
| Vehicle coverage | Synthetic signal names, units, and DBC are not OEM-approved definitions |
| Sample rate | Five-minute SIM data cannot represent high-frequency dynamics or all one-minute buckets |
| Root cause | Heuristic deltas do not account for a validated vehicle-specific baseline or causal interactions |
| Change point | Rolling max-delta is sensitive to data gaps, seasonality, and the selected window |
| Model | Optional 0.5B model quality/latency varies by CPU; deterministic keyword routing is intentionally narrow |
| Authorization | Engineer token is a local stub, not production identity, rotation, or access control |
| IPC | Unix domain socket requires a Linux container runtime; no Windows named-pipe transport is implemented |
| SocketCAN | Host SocketCAN is Linux-specific; live rollups are periodic and the sample DBC is illustrative |
| Operations | No OTA update, key management, secure boot, watchdog, health degradation strategy, or production logging policy |
| Verification | Tests cover fixture scenarios, not vehicle hardware, functional safety, load, fuzzing, or cybersecurity certification |

Docker isolation here is prototype-level. A production vehicle deployment should use a hypervisor with a one-way gateway between safety-relevant domains, plus the required ISO 26262 lifecycle, threat analysis, and platform-specific security validation. This project is not safety-certified and must not control the vehicle.