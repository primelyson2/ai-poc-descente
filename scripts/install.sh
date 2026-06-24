#!/usr/bin/env bash
# 초기 설치 — Python 검증 + uv 설치 + 의존성 동기화
set -e

cd "$(dirname "$0")/.."

echo "=== Oracle AI Database Test Tool — install ==="

# 1. Python 3.11+ 확인
if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 가 설치되어 있지 않습니다."
  echo "  Oracle Linux/RHEL:  sudo dnf install -y python3.11"
  echo "  Ubuntu/Debian:      sudo apt install -y python3.11"
  exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  echo "[ERROR] Python 3.11+ 필요. 현재: $PY_VER"
  exit 1
fi
echo "[OK] Python $PY_VER"

# 2. uv 설치
if ! command -v uv >/dev/null 2>&1; then
  echo "[INSTALL] uv 설치 중..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # 새 셸 없이도 사용 가능하도록 PATH 즉시 갱신
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "[OK] uv $(uv --version)"

# 3. 의존성 동기화
echo "[SYNC] 의존성 설치 중..."
uv sync

# 4. 설정/Wallet 점검
echo
echo "--- 설정 점검 ---"
if [ ! -f config.yaml ]; then
  echo "[WARN] config.yaml 이 없습니다. config.yaml.example 을 복사해 작성하세요."
  echo "       cp config.yaml.example config.yaml && vi config.yaml"
else
  echo "[OK]   config.yaml 존재"
fi

if [ ! -d wallets ] || [ -z "$(ls -A wallets 2>/dev/null)" ]; then
  echo "[WARN] wallets/ 디렉토리에 ADB Wallet 이 없습니다."
  echo "       mkdir -p wallets/<db-name> && unzip Wallet_<db-name>.zip -d wallets/<db-name>/"
else
  echo "[OK]   wallets/ 디렉토리 존재 — 내용: $(ls wallets)"
fi

echo
echo "[DONE] 설치 완료."
echo "       실행:  bash scripts/run.sh"
echo "       종료:  bash scripts/stop.sh"
