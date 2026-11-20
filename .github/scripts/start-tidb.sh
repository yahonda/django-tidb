#!/bin/bash
# Copyright 2026 PingCAP, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# See the License for the specific language governing permissions and
# limitations under the License.

# Start a local TiDB cluster (PD + TiKV + TiDB, optionally TiFlash) with
# `tiup playground` in the background and wait until it is ready.
#
# Usage: start-tidb.sh <tidb-version> [tiflash-count]

set -euo pipefail

TIDB_VERSION="${1:?usage: start-tidb.sh <tidb-version> [tiflash-count]}"
TIFLASH_COUNT="${2:-0}"
TIMEOUT_SECONDS="${TIDB_START_TIMEOUT:-600}"
MAX_ATTEMPTS="${TIDB_START_ATTEMPTS:-3}"
TIUP_MIRROR="https://tiup-mirrors.pingcap.com"
LOG_FILE="${TIDB_PLAYGROUND_LOG:-${RUNNER_TEMP:-/tmp}/tiup-playground.log}"

if ! command -v tiup >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf "$TIUP_MIRROR/install.sh" | sh
  export PATH="$HOME/.tiup/bin:$PATH"
  if [[ -n "${GITHUB_PATH:-}" ]]; then
    echo "$HOME/.tiup/bin" >> "$GITHUB_PATH"
  fi
fi

# Start the playground once and wait for it.
# Returns 0 when ready, 1 when the playground exited or timed out.
start_once() {
  nohup tiup playground "$TIDB_VERSION" \
    --mode tidb \
    --db 1 --pd 1 --kv 1 --tiflash "$TIFLASH_COUNT" \
    --db.port 4000 \
    --without-monitor \
    > "$LOG_FILE" 2>&1 &
  local pid=$!

  for ((i = 0; i < TIMEOUT_SECONDS; i += 5)); do
    if grep -q "TiDB Playground Cluster is started" "$LOG_FILE"; then
      echo "TiDB is ready after ${i}s."
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "tiup playground exited after ${i}s."
      return 1
    fi
    sleep 5
  done

  echo "TiDB did not start within ${TIMEOUT_SECONDS}s."
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  return 1
}

for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
  echo "Starting TiDB $TIDB_VERSION (tiflash=$TIFLASH_COUNT), attempt $attempt/$MAX_ATTEMPTS..."
  if start_once; then
    exit 0
  fi
  echo "Playground log:"
  cat "$LOG_FILE"
  if ((attempt < MAX_ATTEMPTS)); then
    # Mirror metadata (root.json) fetched while the mirror is being updated
    # can fail signature checks; re-initialize it before retrying.
    tiup mirror set "$TIUP_MIRROR" || true
    sleep $((attempt * 15))
  fi
done

echo "Failed to start TiDB after $MAX_ATTEMPTS attempts."
exit 1
