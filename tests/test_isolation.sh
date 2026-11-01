#!/bin/sh
set -eu

engine=$(docker compose ps -q engine)
ui=$(docker compose ps -q ui)
[ -n "$engine" ] && [ -n "$ui" ] || { echo "FAIL: start VehicleGPT before isolation-test"; exit 1; }
failures=0

if docker exec "$engine" ping -c 1 -W 1 1.1.1.1 >/dev/null 2>&1; then
  echo "FAIL: engine ping reached an external network address"; failures=1
else
  echo "PASS: engine ping failed (network_mode: none)"
fi

if docker exec "$engine" python -c 'import sqlite3; c=sqlite3.connect("file:/data/vehicle.db?mode=ro",uri=True); c.execute("PRAGMA query_only=ON"); c.execute("INSERT INTO events(ts,type,severity,context_json) VALUES(\"x\",\"x\",\"x\",\"{}\")")' >/dev/null 2>&1; then
  echo "FAIL: read-only AI database write unexpectedly succeeded"; failures=1
else
  echo "PASS: engine SQL write rejected by read-only connection"
fi

for container in "$engine" "$ui"; do
  if docker exec "$container" python -c 'import os; assert not any(name.startswith("can") for name in os.listdir("/sys/class/net"))' >/dev/null 2>&1; then
    echo "PASS: no CAN interface visible in $container"
  else
    echo "FAIL: CAN interface present or could not be checked in $container"; failures=1
  fi
done

memory=$(docker inspect --format '{{.HostConfig.Memory}}' "$engine")
cpus=$(docker inspect --format '{{.HostConfig.CpusetCpus}}' "$engine")
[ "$memory" = "1048576000" ] && [ "$cpus" = "0,1" ] || { echo "FAIL: engine limits memory=$memory cpuset=$cpus"; failures=1; }
echo "Engine resource configuration: memory=$memory bytes cpuset=$cpus"
docker stats --no-stream "$engine" "$ui"

exit "$failures"