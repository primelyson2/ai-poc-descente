#!/usr/bin/env bash
# 서버 기동 — 환경변수 PORT/HOST 로 포트/바인드 IP 변경 가능 (기본 0.0.0.0:8000)
set -e

cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

# config.yaml 필수
if [ ! -f config.yaml ]; then
  echo "[ERROR] config.yaml 이 없습니다. bash scripts/install.sh 후 작성하세요."
  exit 1
fi

# 포트 점유 확인
if command -v lsof >/dev/null 2>&1; then
  if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[ERROR] 포트 $PORT 가 점유 중입니다."
    echo "        먼저 종료:  bash scripts/stop.sh"
    exit 1
  fi
fi

# uv 가 $PATH 에 없으면 ~/.local/bin 시도
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "[START] uvicorn app.main:app on $HOST:$PORT"
exec uv run uvicorn app.main:app --host "$HOST" --port "$PORT" --workers 1
