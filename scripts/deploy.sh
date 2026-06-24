#!/usr/bin/env bash
# 로컬 → VM 소스 전송 헬퍼.
# 사용: bash scripts/deploy.sh <user>@<host> [<remote-dir>]
#   예: bash scripts/deploy.sh ec2-user@10.0.1.42 ~/oracle-ai-tool
#
# 비밀 파일 (config.yaml, wallets/) 은 전송하지 않는다.
# 대신 VM 에서 별도로 작성/배치.
set -e

if [ $# -lt 1 ]; then
  echo "사용법: bash scripts/deploy.sh <user>@<host> [<remote-dir>]"
  exit 1
fi

REMOTE="$1"
REMOTE_DIR="${2:-~/oracle-ai-tool}"

cd "$(dirname "$0")/.."

# 원격 디렉토리 보장
ssh "$REMOTE" "mkdir -p $REMOTE_DIR"

echo "[RSYNC] → $REMOTE:$REMOTE_DIR"
rsync -avz --delete \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='wallets/' \
  --exclude='config.yaml' \
  --exclude='.git/' \
  --exclude='*.log' \
  ./ "$REMOTE:$REMOTE_DIR/"

echo
echo "[DONE] 전송 완료."
echo "  VM 측 다음 단계:"
echo "    ssh $REMOTE"
echo "    cd $REMOTE_DIR"
echo "    bash scripts/install.sh"
echo "    cp config.yaml.example config.yaml && vi config.yaml      # ADB 접속정보 입력"
echo "    mkdir -p wallets/<db-name>"
echo "    unzip Wallet_<db-name>.zip -d wallets/<db-name>/"
echo "    bash scripts/run.sh"
