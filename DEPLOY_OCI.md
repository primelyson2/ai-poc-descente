# OCI Resource Manager 배포 가이드

GitHub 리포(`select-ai-test`)를 소스로 삼아 **OCI Resource Manager** 로 Oracle Linux 인스턴스에 본 도구(Oracle AI Database Test Tool)를 원클릭 배포하기 위한 작업 내용과 절차를 정리한 문서입니다.

> 요약: README 상단의 **Deploy to Oracle Cloud** 버튼 → RM 이 GitHub 아카이브 zip 을 스택으로 로드 → **Working directory 에서 `deploy/http`(인증서 불필요) 또는 `deploy/https`(LB+인증서) 선택** → 변수 입력 후 Apply → 인스턴스 부팅 시 `git clone → uv sync → systemd 기동` 자동 수행 → `app_url`(HTTP) / `https_url`(HTTPS) 접속 → **[Database 관리]** 화면에서 ADB 등록.

> **두 가지 배포 변형** (스택 폴더로 분리, 각 폴더가 독립 스택):
> - **`deploy/http/`** — Load Balancer·인증서 **없이** 인스턴스 공인 IP 의 앱 포트로 직접(HTTP) 접속. 사전 준비가 가장 적어 빠른 데모/내부 PoC 에 적합.
> - **`deploy/https/`** — 공용 Load Balancer 가 TLS 종단(443) → 인스턴스 :8000 으로 전달. **인증서 OCID + IAM 정책 + 443/80 인바운드** 필요.

---

## 1. 배포 아키텍처

```
[사용자 브라우저]
   │  README 의 "Deploy to Oracle Cloud" 버튼 클릭
   ▼
https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=
        https://github.com/primelyson2/select-ai-test/archive/refs/heads/main.zip
   │
   ▼
[OCI Resource Manager]  ── Working directory 선택: deploy/http | deploy/https ──┐
   │  <폴더>/main.tf / variables.tf / outputs.tf            │
   │  <폴더>/schema.yaml(입력 UI)                            │
   ▼                                                        ▼
[프로비저닝되는 리소스]                  [컴퓨트 부팅: cloud-init.tftpl]
   • Compute (Oracle Linux 8/9)             1. dnf install git python3.11 lsof
     - 기존 VCN/서브넷 선택 사용             2. git clone <repo> → /opt/select-ai-test
     - 공인 IP 옵션                          3. uv 설치 + uv sync (.venv)
   • Load Balancer (공용, flexible)         4. systemd 서비스 등록·기동
     ── deploy/https 에서만 생성 ──         5. firewalld 포트 개방
     - 443 리스너 = OCI 인증서(OCID) TLS
     - 백엔드 = 인스턴스 private_ip:8000
   (VCN/서브넷/보안목록은 생성하지 않음)
   │
   ▼
[Outputs]
   • deploy/http  → app_url   = http://<공인IP>:8000  (LB 없이 인스턴스 직접)
   • deploy/https → https_url = https://<LB IP>       (HTTPS 443 → LB TLS 종단 → 인스턴스 8000)
   →  접속 후 [Database 관리]에서 ADB 등록
```

핵심 설계: 앱이 **`config.yaml` 없이도 기동**되므로(빈 설정 허용), 배포 후 화면의 **[Database 관리]** 메뉴에서 Wallet zip 업로드만으로 첫 DB 를 등록할 수 있습니다. 비밀(접속정보·Wallet)을 Terraform/리포에 넣지 않습니다.

---

## 2. 추가/변경된 파일

스택 구성 파일은 방식별로 **`deploy/http/`, `deploy/https/`** 폴더에 들어 있습니다 (각 폴더가 독립 스택, 동일 파일명):

| 파일 | `deploy/http/` (HTTP) | `deploy/https/` (HTTPS) |
|---|---|---|
| `main.tf` | provider + 컴퓨트 인스턴스(**기존 VCN/서브넷 선택**) + 최신 OL 이미지 조회. **LB 없음** | 좌측 + **HTTPS Load Balancer**(443 리스너=OCI 인증서 OCID, 백엔드 :8000, 헬스체크, 80→443 리다이렉트) |
| `variables.tf` | 인스턴스 이름/shape/OCPU·메모리/OS/SSH 키/VCN·서브넷/공인 IP/포트/리포 | 좌측 + **certificate_ocid / https_port / lb_*** |
| `outputs.tf` | `app_url` / `public_ip` / `private_ip` / `ssh_command` | 좌측 + `https_url` / `load_balancer_ip` |
| `cloud-init.tftpl` | 부팅 부트스트랩 — `git clone → uv sync → systemd 등록·기동 → 방화벽 개방` | **동일** (두 폴더 같은 내용) |
| `schema.yaml` | 변수 입력 UI (HTTPS 그룹 **없음**, primaryOutput=`app_url`) | 변수 입력 UI (HTTPS 그룹 포함, primaryOutput=`https_url`) |

함께 변경한 파일:

| 파일 | 변경 내용 |
|---|---|
| `README.md` | 상단에 **Deploy to Oracle Cloud** 버튼 + §4 "OCI Resource Manager 배포" 절 추가 |
| `.gitignore` | Terraform 로컬 산출물(`.terraform/`, `*.tfstate`, `*.tfvars` 등) 제외 |
| `app/config.py` | `config.yaml` 이 없거나 비어 있어도 빈 설정으로 기동 (신규 인스턴스 부트스트랩 지원) |

> 비밀 파일(`config.yaml`, `wallets/`)은 기존 `.gitignore` 로 계속 제외됩니다 — 리포에 올라가지 않습니다.

---

## 3. Deploy 버튼 / URL

README 상단 버튼 마크다운:

```markdown
[![Deploy to Oracle Cloud](https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg)](https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/primelyson2/select-ai-test/archive/refs/heads/main.zip)
```

동작 URL:

```
https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/primelyson2/select-ai-test/archive/refs/heads/main.zip
```

- `zipUrl` 은 GitHub 의 **브랜치 아카이브 zip** 주소입니다. RM 이 이 zip 을 받아 Terraform 구성으로 인식합니다.
- **HTTP/HTTPS 버튼의 zipUrl 은 동일**합니다. Terraform 구성이 루트가 아닌 `deploy/http`·`deploy/https` 두 폴더에 있으므로, RM 의 **Working directory** 드롭다운에서 폴더를 골라 방식을 결정합니다. (Deploy 버튼 URL 은 working directory 를 미리 지정하는 파라미터를 지원하지 않습니다 — `zipUrl` 만 가능.)
- 다른 리포/브랜치로 바꾸려면 경로와 `…/refs/heads/<branch>.zip` 을 수정하세요.
- **공개(public) 리포** 기준입니다. private 리포는 RM 이 zip 을 받지 못하고 인스턴스의 `git clone` 도 실패합니다(별도 토큰/PAR 방식 필요).

---

## 4. 사전 준비

- OCI 테넌시 + 인스턴스를 만들 **구획(Compartment)** 및 적절한 IAM 권한
- 사용할 리전의 **컴퓨트 한도(서비스 리밋)** — 선택한 shape 기준 여유
- **SSH 공개키** (`~/.ssh/id_rsa.pub`) — *선택*. SSH 접속하려면 준비, 없으면 생성:
  ```bash
  ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa
  cat ~/.ssh/id_rsa.pub
  ```
- 소스를 올릴 **공개 GitHub 리포** (`select-ai-test`)

---

## 5. 배포 절차

### 단계 0. (최초 1회) GitHub 에 소스 푸시
`project/` 폴더가 **리포 루트**가 되도록 푸시합니다. `config.yaml`·`wallets/` 는 `.gitignore` 로 자동 제외됩니다.

```bash
cd project
git init -b main
git add .
git commit -m "Initial: Oracle AI DB Test Tool + OCI RM stack"
git remote add origin https://github.com/primelyson2/select-ai-test.git
git push -u origin main
```

### 단계 1. Deploy 버튼 클릭 → Stack information
- GitHub 리포 README 의 **Deploy to Oracle Cloud** 버튼 클릭 → OCI 로그인 → **Create stack** 진입(구성 자동 로드)
- **Working directory** 드롭다운에서 **`deploy/http`**(인증서 불필요·간편) 또는 **`deploy/https`**(LB+인증서) 선택 → 선택한 폴더의 `schema.yaml` 로 변수 폼이 구성됨
- "I have reviewed and accept the Oracle Terms of Use" 체크 → **Next**

### 단계 2. Configure variables

| 그룹 | 변수 | 설명 | 기본값 |
|---|---|---|---|
| 일반 | **구획 (Compartment)** | 리소스를 만들 구획 | — (선택) |
| 컴퓨트 | **컴퓨트 인스턴스 표시 이름** | 생성될 인스턴스 이름 | `select-ai-test` |
| 컴퓨트 | **Instance shape** | 컴퓨트 형상 | `VM.Standard.E5.Flex` |
| 컴퓨트 | **OCPU 수 / 메모리 GB** | Flex shape 전용 (고정 shape 은 무시) | 1 / 8 |
| 컴퓨트 | **Oracle Linux 버전** | 9 또는 8 | `9` |
| 컴퓨트 | **가용 도메인** | 비우면 첫 번째 AD 자동 사용 | (빈값) |
| 컴퓨트 | **SSH public key** *(선택)* | `.pub` 파일 업로드 또는 붙여넣기 (비우면 미등록) | (빈값) |
| 네트워크 | **Virtual cloud network (VCN)** | 사용할 **기존 VCN** 선택 | — (필수) |
| 네트워크 | **Subnet** | 인스턴스가 들어갈 **기존 서브넷** 선택 | — (필수) |
| 네트워크 | **공인 IP 할당** | public 서브넷이면 체크, private 이면 해제 | `true` |
| 네트워크 | **앱 포트** | 서비스 포트 (서브넷 보안목록에서 허용 필요) | `8000` |
| HTTPS *(deploy/https 전용)* | **Certificate OCID** *(필수)* | OCI Certificates 서비스 인증서 OCID (배포 리전 동일) | — |
| HTTPS *(deploy/https 전용)* | **HTTPS 포트 / 80→443 리다이렉트** | LB TLS 종단 포트 / HTTP 리다이렉트 | `443` / 켬 |
| HTTPS *(deploy/https 전용)* | **LB 서브넷(선택) / Private LB / 대역폭** | 비우면 인스턴스 서브넷 재사용 | (빈값) / 공용 / 10·10 |
| 소스 | **Git 리포지토리 URL / 브랜치** | 소스 위치 | 위 리포 / `main` |

> **`deploy/http` 를 골랐다면 위 HTTPS 행은 폼에 나타나지 않습니다.** (인증서·LB 불필요)
> **네트워크는 생성하지 않고 기존 VCN/서브넷을 선택**합니다. 선택한 서브넷의 보안 목록에서 인바운드를 미리 허용하세요 — HTTP: **8000·SSH(22)**, HTTPS: 추가로 **443(및 80)** + [§8 보안 메모](#8-보안-메모) 의 IAM 정책.
> **Always Free** 로 쓰려면 Shape 를 `VM.Standard.A1.Flex`(ARM, 권장) 또는 `VM.Standard.E2.1.Micro` 로 변경. oracledb 는 Thin 모드라 ARM 에서도 동작합니다.

### 단계 3. Review → Create → Apply
- **Create** 시 "Run apply" 를 켜두거나, 스택 생성 후 **Apply** 버튼 클릭
- Apply Job 로그 끝의 **Outputs** 에서 접속 URL 확인 — HTTP: `app_url`(예: `http://<공인IP>:8000`) · HTTPS: `https_url`(예: `https://<LB IP>`)

### 단계 4. 첫 DB 등록
- 브라우저로 위 URL(`app_url` 또는 `https_url`) 접속 → 좌측 **[Database 관리]** 메뉴
- **+ 새 데이터베이스** → ADB Wallet(zip) 업로드 → 사용자/비밀번호/DSN 입력 → **저장** → **연결 테스트**
- 헤더 드롭다운에 등록되면 각 메뉴에서 테스트 시작

> 부팅 후 `git clone`+`uv sync` 에 보통 **1~3분** 소요됩니다. 접속이 안 되면 잠시 후 재시도하거나 아래 로그를 확인하세요.

---

## 6. 운영 / 재배포

### 진행·상태 확인 (SSH)
```bash
ssh opc@<공인IP>
sudo tail -f /var/log/select-ai-deploy.log     # 부트스트랩 진행 로그
systemctl status select-ai-test                 # 서비스 상태
journalctl -u select-ai-test -f                 # 앱 로그
```

### 소스 업데이트 후 재기동
```bash
# 로컬: GitHub 에 푸시
git push

# 인스턴스
ssh opc@<공인IP>
cd /opt/select-ai-test && git pull && ~/.local/bin/uv sync
sudo systemctl restart select-ai-test
```

### 깨끗한 재배포 / 정리
- Resource Manager 스택에서 **Destroy** → 다시 **Apply** 하면 새 인스턴스로 재배포
- 더 이상 쓰지 않으면 **Destroy** 로 전체 리소스(VCN/서브넷/인스턴스 등) 제거

---

## 7. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| RM 에서 zip 로드 실패 | 리포가 private 이거나 브랜치명이 다름. public 인지, `…/refs/heads/<branch>.zip` 의 브랜치가 맞는지 확인 |
| `app_url` 접속 안 됨 (부팅 직후) | clone+sync 진행 중. 1~3분 후 재시도. `/var/log/select-ai-deploy.log` 확인 |
| `https_url` 접속 안 됨 | ① 서브넷 보안목록에 **443**(필요시 80) 인바운드 ② LB→인스턴스 **8000** 허용 ③ **IAM 정책**(아래) 미설정으로 인증서 미참조 ④ 콘솔 LB → Backend Sets health 가 OK 인지 확인 |
| 서비스/소스 자체 접속 안 됨 | ① 서브넷 보안목록 app_port(8000)/22 ② 공인 IP/서브넷 public ③ 인스턴스 firewalld ④ `systemctl status select-ai-test` 순서로 점검 |
| LB health "Critical" | 인스턴스 8000 미기동 또는 서브넷이 LB→인스턴스 8000 을 막음. `curl localhost:8000`(VM 내부)·보안목록 확인 |
| `git clone` 권한 오류 | private 리포. public 으로 전환하거나 토큰 방식 적용 필요 |
| 이미지 조회 실패/빈 결과 | 선택한 shape 에서 해당 OL 버전 이미지가 없을 수 있음. OS 버전(9↔8) 또는 shape 변경 |
| 컴퓨트 한도 초과 | 리전/구획의 서비스 리밋 부족. 다른 shape 선택 또는 한도 증설 요청 |

---

## 8. 보안 메모

### HTTPS 사전 준비 (필수 — Terraform 밖)
LB/리스너/백엔드는 Terraform 이 만들지만, 다음 2가지는 **반드시 별도로** 준비해야 합니다.

1. **보안 목록 인바운드** — 선택한 서브넷의 Security List/NSG 에 추가:
   - `443/TCP`(80→443 리다이렉트 쓰면 `80/TCP` 도) ← 클라이언트 → LB
   - `8000/TCP` ← LB → 인스턴스 (이미 열려 있으면 충족)
   - `22/TCP` ← SSH (선택)
2. **IAM 정책** — LB 가 Certificates 서비스 인증서를 읽도록 1회 생성(관리자):
   ```
   Allow any-user to read leaf-certificate-bundles in compartment <구획> where all { request.principal.type = 'loadbalancer' }
   ```
   (정확한 표현은 OCI 문서 "Load Balancer + Certificates Service" 로 확인. 정책 누락 시 LB 가 인증서를 못 읽어 리스너가 동작하지 않음)

### 일반
- 인바운드 허용은 **선택한 기존 서브넷의 보안 목록(Security List/NSG)** 에서 관리합니다. 운영/외부 노출 시 인바운드를 사내 IP 대역으로 좁히세요.
- **Private 인증서 신뢰:** Private CA 발급 인증서는 브라우저가 기본 신뢰하지 않아 경고가 뜹니다. 클라이언트가 해당 **Private CA 루트를 신뢰 저장소에 추가**해야 경고 없이 접속됩니다(내부망용 정상).
- TLS 는 LB 에서 종단되고 **LB→인스턴스 구간은 평문 HTTP(8000)** 입니다. 같은 VCN 사설 구간이라 일반적이나, 종단간 암호화가 필요하면 백엔드도 HTTPS 로 구성하세요.
- **비용:** Flexible LB 는 시간당 과금(최소 10Mbps). 데모 후 미사용 시 **Destroy**.
- ADB 접속정보/Wallet 은 리포·Terraform 에 포함하지 않고, 배포 후 **[Database 관리]** 화면에서 등록합니다. 인스턴스 내부 `/opt/select-ai-test/config.yaml` 및 `wallets/` 에 저장되므로 인스턴스 접근 통제가 곧 비밀 보호입니다.

---

## 9. 검증 상태

- `terraform init -backend=false` + `terraform validate` → **Success** (`deploy/http`, `deploy/https` 각각, oracle/oci provider 기준)
- `terraform fmt -check` → 두 폴더 모두 포맷 정상
- `cloud-init.tftpl` 템플릿 치환 변수 → `repo_url` / `repo_branch` / `app_port` 3개만(나머지 bash `$VAR` 는 보존). 두 폴더 파일 내용 동일(`diff` 확인).
- `schema.yaml` → YAML 파싱 정상 — `deploy/https` 변수 21·그룹 6, `deploy/http` 변수 14·그룹 5(HTTPS 그룹 제거)
- HTTPS Load Balancer(443 리스너=OCI 인증서 OCID) — `deploy/https` 에만 존재, `terraform validate` 로 `certificate_ids`/`ssl_configuration` 필드 검증됨. `deploy/http` 에는 LB/인증서 리소스·변수 없음(validate 통과).
