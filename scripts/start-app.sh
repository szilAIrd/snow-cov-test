#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required to run SnowRoute. Please install Docker Desktop or Docker Engine first." >&2
  exit 1
fi

ensure_docker_running() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi

  echo "Docker is installed but not running. Attempting to start Docker Desktop..."

  if [[ "$(uname -s)" == "Darwin" ]]; then
    if [[ -d "/Applications/Docker.app" ]]; then
      open -a Docker
    elif [[ -d "/Applications/Docker Desktop.app" ]]; then
      open -a "Docker Desktop"
    else
      echo "Docker Desktop could not be found in /Applications. Please install Docker Desktop or start the Docker daemon manually." >&2
      exit 1
    fi

    for i in $(seq 1 90); do
      if docker info >/dev/null 2>&1; then
        return 0
      fi
      sleep 2
    done

    echo "Docker did not start successfully. Please start Docker Desktop manually and try again." >&2
    exit 1
  fi

  echo "Docker is installed but not running. Please start the Docker daemon manually and try again." >&2
  exit 1
}

ensure_docker_running

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is required to run SnowRoute." >&2
  exit 1
fi

printf '\nStarting SnowRoute...\n'
"${COMPOSE[@]}" up --build -d

printf '\nWaiting for backend health check...\n'
READY=0
for i in $(seq 1 60); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done

if [[ "${READY}" -ne 1 ]]; then
  echo "SnowRoute backend did not become healthy in time." >&2
  "${COMPOSE[@]}" ps
  exit 1
fi

if command -v open >/dev/null 2>&1; then
  open "http://localhost"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost" >/dev/null 2>&1 || true
fi

printf '\nSnowRoute is running.\n'
printf 'Browser: http://localhost\n'
printf 'API health: http://localhost:8000/health\n'
printf 'Stop with: %s down\n' "${COMPOSE[@]}"
