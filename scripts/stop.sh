#!/usr/bin/env bash
# 서버 종료 — 환경변수 PORT 로 대상 포트 지정 (기본 8000)
PORT="${PORT:-8000}"

if ! command -v lsof >/dev/null 2>&1; then
  echo "[ERROR] lsof 가 없습니다. sudo dnf install -y lsof  또는  sudo apt install -y lsof"
  exit 1
fi

PID=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)
if [ -z "$PID" ]; then
  echo "[INFO] 포트 $PORT 에서 실행 중인 프로세스 없음"
  exit 0
fi

echo "[STOP] PID $PID 종료 시도..."
kill "$PID"
sleep 2

if kill -0 "$PID" 2>/dev/null; then
  echo "[FORCE] kill -9 $PID"
  kill -9 "$PID"
fi

echo "[OK] 종료 완료"
