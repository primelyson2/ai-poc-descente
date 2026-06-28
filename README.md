# Oracle AI Database Test Tool

Oracle Autonomous Database 23ai 의 **SELECT AI** (`DBMS_CLOUD_AI.GENERATE`), **AI Agent Team** (`DBMS_CLOUD_AI_AGENT.RUN_TEAM`), 그리고 SELECT AI 답변 품질에 영향을 주는 **Object Comment / Annotation 메타데이터** 를 한 화면에서 테스트·관리하는 PoC 도구.

여러 ADB 를 등록해 두고 화면 우측 상단 드롭다운으로 전환하면서 동일한 프롬프트/팀을 **동일 도구로 비교**할 수 있습니다.

> ⚠️ **본 도구는 PoC/데모 목적이며 프로덕션 사용을 보장하지 않습니다.** "있는 그대로(AS IS)" 제공되며 어떠한 보증도 하지 않습니다 (Apache License 2.0, §7·§8 참조).

## ☁️ OCI 원클릭 배포 (Resource Manager)

아래 버튼을 누르면 OCI Resource Manager 의 **Create Stack** 화면으로 이동하며, 이 리포의 Terraform 스택이 자동으로 로드됩니다. 부팅 시 소스를 clone → 의존성 설치 → 서비스 기동까지 자동 수행합니다.

[![Deploy to Oracle Cloud](https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg)](https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/primelyson2/select-ai-test/archive/refs/heads/main.zip)

> 버튼은 **하나**입니다. 배포 방식(HTTP/HTTPS)은 클릭 후 **Create Stack 화면의 `Working directory` 드롭다운에서 폴더를 고르는 것**으로 결정합니다. (Deploy 버튼 URL 은 working directory 를 미리 지정할 수 없어, 두 방식이 같은 zip 을 공유합니다.)

| | **옵션 A — HTTP** (인증서 불필요, 간편) | **옵션 B — HTTPS** (Load Balancer + 인증서) |
|---|---|---|
| Working directory | **`deploy/http`** 선택 | **`deploy/https`** 선택 |
| 입력 | 구획/네트워크만 | + **인증서 OCID** 등 |
| 동작 | LB 없이 인스턴스 공인 IP 직접 접속 | 공용 LB 가 TLS 종단 → 인스턴스 `:8000` 전달 |
| 접속 URL | `app_url` = `http://<공인IP>:8000` | `https_url` = `https://<LB IP>` |
| 사전 준비 | 서브넷 보안 목록에 **앱 포트(기본 8000) 인바운드**만 | 서브넷에 443(및 80) 인바운드 + LB 가 인증서 읽도록 **IAM 정책** 1회 ([HTTPS 사전 준비](#https-사전-준비-필수)) |
| 권장 | 빠른 데모/내부 PoC (평문 HTTP) | 외부 노출/TLS 필요 시 |

배포가 끝나면 스택 Outputs 의 `app_url`(HTTP) 또는 `https_url`(HTTPS) 로 접속 → **[Database 관리]** 메뉴에서 ADB Wallet 을 업로드해 첫 DB 를 등록합니다. 자세한 절차는 [§4. OCI Resource Manager 배포](#4-oci-resource-manager-배포) 또는 별도 문서 **[DEPLOY_OCI.md](DEPLOY_OCI.md)** 참조.

---

## 1. 주요 기능

### [메뉴 1] AI Profile Test
- `USER_CLOUD_AI_PROFILES` / `USER_CLOUD_AI_PROFILE_ATTRIBUTES` 로부터 Profile 목록과 속성을 조회.
- **Tab 1 — Profile 목록 / 속성**
  - 각 Profile 행 우측의 `AI Test` 버튼으로 즉시 단일 호출 테스트 (프롬프트 + Action 선택 → 응답·소요시간)
  - 속성 그리드의 Value 셀을 직접 편집 후 `저장` → `DBMS_CLOUD_AI.SET_ATTRIBUTE` 호출
  - 하단 헤더의 `AI Profile 구문 생성` 버튼 → 현재 속성으로 `dbms_cloud_ai.create_profile(...)` PL/SQL 블록 자동 생성 + 복사
- **Tab 2 — 속도 측정 및 비교**
  - 동일 프롬프트로 여러 Profile × 반복 횟수 만큼 `DBMS_CLOUD_AI.GENERATE` 호출
  - 회차별 응답시간 / 평균 / 최소 / 최대를 표 + Chart.js 막대그래프로 시각화
  - `runsql` / `narrate` / `showsql` 선택 시 `object_list` 가 설정된 Profile 만 자동 필터
  - 캐시 회피용으로 회차 번호만큼 `.` 을 프롬프트 끝에 자동 추가

### [메뉴 2] AI Agent Team Test
- `USER_AI_AGENT_TEAMS` / `_AGENTS` / `_TASKS` / `_TOOLS` 와 각 `*_ATTRIBUTES` 를 단일 batch 쿼리로 조회 (`asyncio.gather` 로 병렬화).
- **Tab 1 — Team / Agent / Task / Tool 트리**
  - Team → Agent → Task → Tool 4 레벨 계층 트리
  - 각 노드의 type 배지 + role / instruction 요약 inline 표시
  - 노드 선택 시 하단에 속성 그리드 → Value 직접 편집 후 `저장` → `DBMS_CLOUD_AI_AGENT.SET_ATTRIBUTE` 호출
- **Tab 2 — Team 실행 및 단계별 속도 추적**
  - PL/SQL 블록 (`CREATE_CONVERSATION` + `RUN_TEAM`) 실행, CLOB 결과 + `conversation_id` 반환
  - `USER_AI_AGENT_TEAM_HISTORY` / `_TASK_HISTORY` / `_TOOL_HISTORY` 의 `START_DATE` / `END_DATE` 로 Gantt 스타일 단계 타임라인 재구성
  - Raw 로그 (대화 프롬프트 / Task 이력 / Tool 호출 횟수·시간) 접이식 표

### [메뉴 3] Profile Object Comment & Annotation
- Profile 의 `object_list` 속성 (JSON 배열) 을 파싱하여 등록 테이블 목록 표시.
- 테이블 클릭 시 `ALL_TAB_COMMENTS` / `ALL_COL_COMMENTS` / `USER_ANNOTATIONS_USAGE` 기반의 테이블·컬럼 메타데이터 그리드.
- **테이블 레벨**: Comment textarea 수정 + Annotation (1:N) 관리 모달 (`ALTER TABLE ... ANNOTATIONS (ADD OR REPLACE / DROP ...)`)
- **컬럼 레벨**: 컬럼별 Comment 인라인 편집 → `Comment 일괄 저장`, Annotation 모달로 개별 추가/삭제
- Identifier (owner/table/column/annotation name) 는 `^[A-Z][A-Z0-9_$#]*$` 정규식으로 화이트리스트 검증 후 SQL 보간. Comment / Annotation 값은 single-quote 이스케이프 후 SQL literal 로 삽입.

### [메뉴 4] Database 관리
- 테스트 대상 ADB 를 **화면에서 직접 등록·수정·삭제** (config.yaml 을 손으로 편집하지 않아도 됨).
- **Wallet zip 업로드** — OCI 콘솔에서 내려받은 Instance Wallet zip 을 그대로 업로드하면 `wallets/<이름>/` 에 자동 압축 해제.
- 업로드 즉시 `tnsnames.ora` 를 파싱해 **DSN 드롭다운** (`..._high` / `_medium` / `_low` 등) 을 자동 채움.
- `연결 테스트` 버튼으로 풀을 재초기화하여 접속 가능 여부 즉시 확인 (성공/오류 ORA 메시지 표시).
- 저장 시 `config.yaml` 을 다시 쓰고 해당 DB 풀을 재기동 → 헤더 드롭다운에 즉시 반영 (서버 재시작 불필요).
- 비밀번호 / Wallet 비밀번호는 응답에 노출하지 않으며, 수정 시 비워두면 기존 값을 유지.

### [메뉴 5] 접근 키 관리
- 관리자가 접근 키와 관리자 이메일을 설정·관리하는 화면.
- 구현·운영 세부는 별도 내부 문서 `SECURITY_INFO.md` 참조(저장소 미포함).

### [확장 메뉴] AI SQL Tuning Assistant
- OADT2의 독립 extension 화면으로, SQL을 입력하면 ADB ORDS `ASTA_PKG.ANALYZE_SQL`을 호출해 상세 SQL 튜닝 결과서를 생성합니다.
- 브라우저는 외부 ORDS/ASTA 주소를 직접 호출하지 않고 OADT2 same-origin API를 사용합니다.
  - `POST /api/asta/analyze` → ADB ORDS `ASTA_PKG.ANALYZE_SQL` 호출 결과 pass-through (Python-local SQL 실행 없음)
  - `GET /api/asta/profiles` → ADB ORDS `ASTA_PKG.LIST_PROFILES` 호출 결과 pass-through
- 사용자는 endpoint/source DB를 선택하지 않습니다. Source DB는 ADB의 `ASTA_SOURCE_CONNECTIONS` 허용 목록에서 조회됩니다.
- ADB PL/SQL package(`ASTA_PKG`)가 SQL Guard, Source evidence 수집(DB Link → Source helper package), SQL Tuning Advisor, Vector KB 검색/저장, LLM 튜닝, 보고서 생성을 담당합니다.
- Source BaseDB 실제 XPLAN/metrics는 Source helper package(`db/source/asta_source_pkg.sql`)를 ADB DB Link로 호출해 수집합니다.
- 모바일에서는 SQL 입력창을 full-width로 표시하고, 수행 이력은 입력/실행 영역 아래에 표시합니다.
- 상세 사용/운영 절차: [`docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md`](docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md)
- 내부 API/Procedure/순서도: [`docs/OADT2_ASTA_ARCHITECTURE.md`](docs/OADT2_ASTA_ARCHITECTURE.md)
- 문서 맵: [`docs/README.md`](docs/README.md)

---

## 2. 기술 스택

| 항목 | 내용 |
|---|---|
| Backend | Python 3.11+ / FastAPI (async) |
| Frontend | Vanilla HTML / CSS / JavaScript (프레임워크 미사용) + Chart.js (CDN) |
| DB | Oracle Autonomous Database 23ai |
| DB 드라이버 | `python-oracledb` **Thin mode** + Wallet (mTLS, Instant Client 불필요) |
| 다중 DB | `config.yaml` 의 `databases:` 리스트 + `X-Database` 헤더 |
| 패키지 관리 | `uv` |
| ASTA 연동 | ADB ORDS `ASTA_PKG.ANALYZE_SQL` — FastAPI는 same-origin thin proxy, Python-local SQL/XPLAN/LLM 실행 없음 |

---

## 3. 로컬 개발

### 사전 준비
- **Python 3.11+**
- **uv** — `curl -LsSf https://astral.sh/uv/install.sh | sh` 또는 `brew install uv`
- **Oracle ADB Wallet** — OCI 콘솔 > Autonomous Database > DB Connection > **Download Wallet (Instance Wallet)**

### 설정 파일 작성
```bash
cp config.yaml.example config.yaml
vi config.yaml
```
다중 DB 예시는 `config.yaml.example` 참조. 필수 키:
- `name` / `label` — UI 헤더 드롭다운에 표시되는 이름
- `user` / `password` — DB 사용자
- `dsn` — `tnsnames.ora` 의 alias (예: `ailakehouse_high`)
- `wallet_location` / `config_dir` — Wallet 압축 해제 경로
- `wallet_password` — Wallet 다운로드 시 설정한 비밀번호

### Wallet 배치
```bash
mkdir -p wallets/<db-name>
unzip Wallet_<db-name>.zip -d wallets/<db-name>/
```
`config.yaml` 의 `wallet_location` / `config_dir` 와 일치시킬 것.

### 실행
```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```
브라우저: <http://localhost:8000>

### ASTA 실행 방식

ASTA/SQL Tuning Assistant는 **ADB ORDS/PL/SQL** 경로로 실행됩니다.

```text
브라우저 → POST /api/asta/analyze
         → FastAPI thin proxy (same-origin CORS 우회만 수행)
         → ADB ORDS ASTA_PKG.ANALYZE_SQL
         → Source BaseDB helper package via ADB DB Link
```

FastAPI `/api/asta/*` 라우터는 same-origin thin proxy 역할만 합니다. Python에서 SQL을 직접 실행하거나 XPLAN/metrics를 수집하거나 Vector/LLM/SQLTUNE 워크플로를 수행하지 않습니다.

SQL Guard, Source evidence 수집(`ASTA_SOURCE_PKG.RUN_EVIDENCE` via DB Link), SQL Tuning Advisor, Vector KB, LLM 튜닝, 보고서 생성은 ADB PL/SQL package(`db/adb/asta_pkg.sql` 등)가 담당합니다.

ADB package 설치 위치: `db/adb/`, Source helper 설치 위치: `db/source/`, ORDS module: `db/ords/`.

> 비밀번호, credential secret, wallet, private key는 환경변수/문서/로그에 노출하지 않습니다.

### 테스트
```bash
node --check static/js/app.js
node --check static/js/extensions/tuning_assistant.js
uv run --with pytest pytest -q
```

### 포트 점유 시
```bash
lsof -i :8000
kill -9 <PID>
```

---

## 4. OCI Resource Manager 배포

GitHub 리포(`select-ai-test`)를 소스로 삼아 **원클릭**으로 Oracle Linux 인스턴스를 만들고 앱을 기동합니다. Terraform 스택은 **방식별로 폴더가 분리**되어 있으며, 각 폴더가 독립적인 완결 스택입니다 (각 폴더에 `main.tf`/`variables.tf`/`outputs.tf`/`schema.yaml`/`cloud-init.tftpl`).

| 폴더 | 방식 | LB/인증서 | 접속 |
|---|---|---|---|
| **`deploy/http/`** | HTTP (간편) | 없음 | `http://<공인IP>:8000` (인스턴스 직접) |
| **`deploy/https/`** | HTTPS (Load Balancer) | 공용 LB + 인증서 OCID | `https://<LB IP>` (LB TLS 종단 → 인스턴스 :8000) |

각 폴더 공통 파일:

| 파일 | 역할 |
|---|---|
| `main.tf` | provider + 컴퓨트 인스턴스(**기존 VCN/서브넷 선택**) + 최신 Oracle Linux 이미지 조회 (https 폴더는 추가로 **HTTPS Load Balancer** 443 리스너·백엔드·헬스체크) |
| `variables.tf` | 입력 변수 (인스턴스 이름, shape, OCPU/메모리, SSH 키, VCN/서브넷, 공인 IP, 포트, 리포 URL/브랜치 — https 폴더는 추가로 **인증서 OCID/HTTPS/LB**) |
| `outputs.tf` | http: `app_url`/`public_ip`/`private_ip`/`ssh_command` · https: 추가로 `https_url`/`load_balancer_ip` |
| `cloud-init.tftpl` | 부팅 스크립트 — `git clone` → `uv sync` → systemd `select-ai-test` 서비스 등록·기동 → 방화벽 개방 (두 폴더 동일) |
| `schema.yaml` | Resource Manager 변수 입력 UI |

> **네트워크는 직접 생성하지 않고 기존 VCN/서브넷을 선택**합니다. 선택한 서브넷의 보안 목록(Security List)에서 **앱 포트(기본 8000)** 와 **SSH(22)** 인바운드를 미리 허용해 두어야 합니다. (VCN/서브넷이 없다면 OCI 콘솔의 *Networking → VCN* 에서 먼저 생성하세요.) HTTPS 는 추가로 **443/80 인바운드 + IAM 정책** 이 필요합니다 ([HTTPS 사전 준비](#https-사전-준비-필수)).

### 동작 방식 (Deploy 버튼)
README 상단의 **Deploy to Oracle Cloud** 버튼(하나)은 아래 URL 로 연결됩니다 — RM 이 GitHub 아카이브 zip 을 받아 스택으로 만듭니다.
```
https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/primelyson2/select-ai-test/archive/refs/heads/main.zip
```
> 루트에는 `.tf` 가 없고 `deploy/http`·`deploy/https` 두 폴더에 들어 있으므로, RM 이 **Working directory** 드롭다운을 띄웁니다. 여기서 고른 폴더가 HTTP/HTTPS 방식을 결정합니다. (Deploy 버튼 URL 은 working directory 를 미리 지정할 수 없습니다.) 다른 리포/브랜치로 바꾸려면 `zipUrl` 의 경로와 `…/refs/heads/<branch>.zip` 을 수정하세요.

### 단계 0. (최초 1회) GitHub 에 소스 푸시
이 `project/` 폴더가 **리포 루트**가 되도록 푸시합니다 (`config.yaml`·`wallets/` 는 `.gitignore` 로 자동 제외 — 비밀이 올라가지 않습니다).
```bash
cd project
git init -b main
git add .
git commit -m "Initial: Oracle AI DB Test Tool + OCI RM stack"
git remote add origin https://github.com/primelyson2/select-ai-test.git
git push -u origin main
```

### 단계 1. Deploy 버튼 클릭 → Stack information
- README 상단 **Deploy to Oracle Cloud** 버튼 클릭 → OCI 로그인 → **Create stack** 진입 (Terraform 구성이 자동 로드됨)
- **Working directory** 드롭다운에서 방식을 선택: **`deploy/http`**(간편) 또는 **`deploy/https`**(인증서/LB). 선택한 폴더의 `schema.yaml` 에 따라 다음 단계의 변수 폼이 달라집니다.
- "I have reviewed and accept the Oracle Terms of Use" 체크 → **Next**

### 단계 2. Configure variables

> 아래 **컴퓨트 / 네트워크 접근 / 애플리케이션 소스** 변수는 두 방식 공통입니다. **HTTPS (Load Balancer)** 변수는 `deploy/https` 를 고른 경우에만 나타납니다 (HTTP 방식은 이 표를 건너뛰고 바로 Apply).

**컴퓨트**
| 변수 | 설명 |
|---|---|
| **구획 (Compartment)** | 리소스를 만들 구획 선택 |
| **컴퓨트 인스턴스 표시 이름** | 생성될 인스턴스 이름 (기본 `select-ai-test`) |
| **Instance shape / OCPU / 메모리** | 기본 `VM.Standard.E5.Flex` · 1 OCPU · 8 GB. *Always Free* 는 `VM.Standard.A1.Flex`(ARM, 권장) |
| **Oracle Linux 버전** | 9 또는 8 |
| **가용 도메인** | 비우면 첫 번째 AD 자동 사용 |
| **SSH public key** *(선택)* | `.pub` 파일 업로드(*Choose SSH key files*) 또는 붙여넣기(*Paste SSH keys*). 비우면 SSH 키 미등록 — 인스턴스 SSH 접속을 하려면 입력 권장 |

**네트워크 접근** (기존 리소스 선택)
| 변수 | 설명 |
|---|---|
| **Virtual cloud network (VCN)** | 사용할 **기존 VCN** 드롭다운 선택 |
| **Subnet** | 인스턴스가 들어갈 **기존 서브넷** 선택 (선택한 VCN 기준으로 목록 필터) |
| **공인 IP 할당** | public 서브넷이면 체크(기본), private 서브넷이면 해제 |
| **앱 포트** | 기본 `8000` — 선택한 서브넷의 보안 목록에서 인바운드 허용 필요 |

**HTTPS (Load Balancer)** *(— `deploy/https` 전용. HTTP 방식은 없음)* — 공용 LB 가 TLS 종단 → 인스턴스 `:8000` 으로 전달
| 변수 | 설명 |
|---|---|
| **Certificate OCID** *(필수)* | OCI **Certificates 서비스** 인증서 OCID. 배포 리전과 동일해야 함 |
| **HTTPS 포트** | 기본 `443` |
| **LB 서브넷 (선택)** | 비우면 인스턴스 서브넷 재사용. 공용 LB 는 public 서브넷 필요 |
| **80 → 443 리다이렉트** | 기본 체크 (HTTP→HTTPS 301) |
| **Private LB / 대역폭** | 기본 공용 · 10/10 Mbps |

> ⚠️ **사전 준비 2가지** (Terraform 밖, [§4 하단](#https-사전-준비-필수) 참조): ① 선택 서브넷 보안목록에 **443(및 80) 인바운드** 추가, ② LB 가 인증서를 읽도록 **IAM 정책** 1회 생성.

**애플리케이션 소스**
| 변수 | 설명 |
|---|---|
| **Git 리포지토리 URL / 브랜치** | 기본값이 위 리포로 채워져 있음 |

### 단계 3. Review → Create
- **Create** 후 자동으로 **Apply** 가 실행되도록 두거나, 스택 생성 후 **Apply** 버튼 클릭
- Apply Job 로그 끝에서 **Outputs** 확인 → **HTTP**: `app_url`(예: `http://<공인IP>:8000`) · **HTTPS**: `https_url`(예: `https://<LB IP>`) 클릭

### 단계 4. 첫 DB 등록
- 브라우저에서 위 URL(`app_url` 또는 `https_url`) 접속 → 좌측 **[Database 관리]** 메뉴
- **+ 새 데이터베이스** → ADB Wallet(zip) 업로드 → 사용자/비밀번호/DSN 입력 → **저장** → **연결 테스트**
- 헤더 드롭다운에 등록한 DB 가 나타나면 각 메뉴에서 테스트 시작

> 인스턴스 부팅 후 `git clone`+`uv sync` 에 보통 1~3분 걸립니다. 접속이 안 되면 잠시 후 재시도하거나, SSH 로 진행 로그를 확인하세요:
> ```bash
> ssh opc@<공인IP>
> sudo tail -f /var/log/select-ai-deploy.log        # 부트스트랩 진행
> systemctl status select-ai-test                    # 서비스 상태
> journalctl -u select-ai-test -f                    # 앱 로그
> ```

### HTTPS 사전 준비 (필수)
> `deploy/https` 방식에만 해당합니다. **HTTP(`deploy/http`) 방식은 인증서·IAM 정책·LB 가 전혀 필요 없고**, 선택한 서브넷 보안 목록에 **앱 포트(기본 8000) 인바운드**만 열면 됩니다.

LB/리스너/백엔드는 Terraform 이 만들지만, 다음 2가지는 **Terraform 범위 밖**이라 별도로 준비해야 합니다.

1. **보안 목록 인바운드** — 선택한 서브넷의 Security List 에 추가 (8000 열었던 방식과 동일):
   - `443/TCP` (리다이렉트 쓰면 `80/TCP` 도) from `0.0.0.0/0`(또는 사내 대역) — 클라이언트 → LB
   - `8000/TCP` — LB → 인스턴스 (이미 열려 있으면 충족)
2. **IAM 정책** — LB 가 Certificates 서비스 인증서를 읽도록 1회 생성(관리자):
   ```
   Allow any-user to read leaf-certificate-bundles in compartment <구획> where all { request.principal.type = 'loadbalancer' }
   ```
   (정확한 표현은 OCI 문서 "Load Balancer + Certificates Service" 로 확인)

> **Private 인증서 신뢰:** Private CA 발급 인증서는 브라우저가 기본 신뢰하지 않아 경고가 뜹니다. 클라이언트가 해당 **Private CA 루트를 신뢰 저장소에 추가**해야 경고 없이 접속됩니다(내부망용 정상 동작).
> **검증:** `curl -vkI https://<LB IP>` 로 TLS 핸드셰이크/인증서 체인 확인, 콘솔 LB → Backend Sets 의 health 가 **OK** 인지 확인.

### 업데이트 / 재배포
소스를 GitHub 에 다시 푸시한 뒤 인스턴스에서:
```bash
ssh opc@<공인IP>
cd /opt/select-ai-test && git pull && ~/.local/bin/uv sync
sudo systemctl restart select-ai-test
```
또는 Resource Manager 스택에서 **Destroy** 후 다시 **Apply** 하면 새 인스턴스로 깨끗하게 재배포됩니다.

---

## 5. 다중 ADB 사용

`config.yaml` 의 `databases:` 리스트에 ADB 여러 개를 등록하면 화면 우측 상단에 드롭다운이 생깁니다.
- 선택값은 `localStorage` 에 저장 → 새로고침 후에도 유지
- 모든 API 호출에 `X-Database: <db-name>` 헤더 자동 첨부
- 한 ADB 의 Wallet 초기화가 실패해도 다른 ADB 는 정상 동작 (실패 항목만 드롭다운에서 비활성화)
- 드롭다운 변경 시 현재 메뉴의 뷰가 새 DB 기준으로 즉시 재조회

---

## 6. 프로젝트 구조

```
project/   (= GitHub 리포 select-ai-test 루트)
├─ README.md                  # 본 문서 (상단에 Deploy to Oracle Cloud 버튼)
├─ DEPLOY_OCI.md              # OCI RM 배포 상세 가이드
├─ deploy/                    # OCI RM 스택 (방식별 폴더 — RM Working directory 로 선택)
│   ├─ http/                  # HTTP 변형 (LB/인증서 없음, 인스턴스 직접 :app_port)
│   └─ https/                 # HTTPS 변형 (공용 LB + 인증서 OCID, TLS 종단)
├─ db/                        # ADB/Source DB PL/SQL/ORDS artifacts (production)
│  ├─ asta/                   # DDL: asta_runs, asta_run_progress, asta_source_connections, vector KB
│  │   ├─ 001_asta_repository.sql          # asta_runs + asta_run_progress (source_db_id included)
│  │   ├─ 002_asta_source_connections.sql  # DB Link allowlist
│  │   ├─ 003_asta_runs_source_db_id.sql   # Additive migration: source_db_id column
│  │   └─ 004_asta_vector_tables.sql       # asta_tuning_cases + asta_tuning_case_chunks (Vector KB)
│  ├─ adb/                    # ADB PL/SQL packages (install on ADB ASTA schema)
│  │   ├─ asta_sql_guard_pkg.sql    # SQL guard: SELECT/WITH only, keyword/terminator check
│  │   ├─ asta_source_bridge_pkg.sql# DB Link bridge to Source helper via allowlist
│  │   ├─ asta_vector_pkg.sql       # Vector KB search/save facade
│  │   ├─ asta_llm_pkg.sql          # DBMS_CLOUD_AI orchestration (tuning + final review)
│  │   ├─ asta_report_pkg.sql       # Markdown/JSON response builder
│  │   └─ asta_pkg.sql              # Main ANALYZE_SQL, LIST_PROFILES, GET_RUN, GET_REPORT
│  ├─ ords/                   # ORDS module (install via ORDS-enabled ASTA schema)
│  │   └─ asta_ords_module.sql      # analyze/profiles/runs/:id/progress/report handlers
│  └─ source/                 # Source BaseDB helper (install on Source BaseDB only)
│      └─ asta_source_pkg.sql       # run_evidence: XPLAN/metrics/SQLTUNE, JSON CLOB
├─ pyproject.toml             # uv 관리 의존성 (fastapi, oracledb, pyyaml, uvicorn, python-multipart)
├─ config.yaml.example        # 설정 샘플 — config.yaml 로 복사 후 작성
├─ config.yaml                # 실제 설정 (git ignored — 비밀 포함)
├─ wallets/                   # ADB Wallet (git ignored)
│   └─ <db-name>/             # tnsnames.ora, cwallet.sso, ewallet.pem 등
├─ app/
│  ├─ main.py                 # FastAPI 엔트리 + lifespan 으로 풀 초기화
│  ├─ config.py               # config.yaml 로더 (다중 ADB)
│  ├─ db.py                   # 비동기 풀 dict + fetch_all/fetch_one/execute
│  ├─ deps.py                 # current_db dependency (X-Database 헤더 검증)
│  └─ routers/
│     ├─ asta_proxy.py        # ASTA same-origin thin proxy → ADB ORDS (Python-local 실행 없음)
│     ├─ databases.py         # 메뉴 4 — DB 목록/등록/수정/삭제/연결테스트 + Wallet zip 업로드
│     ├─ profiles.py          # 메뉴 1 — Profile/Attributes/Benchmark + objects(stub→실DB)
│     ├─ agents.py            # 메뉴 2 — Tree(batch)/Detail/Run/Timeline/SET_ATTRIBUTE
│     └─ objects.py           # 메뉴 3 — Metadata/Comment/Annotation DDL
├─ static/
│  ├─ index.html
│  ├─ css/  (redwood.css, layout.css)
│  └─ js/   (app.js, api.js, db_selector.js, views/*, components/*)
│     └─ extensions/
│        └─ tuning_assistant.js     # ASTA UI extension (passes ADB ORDS progress/report)
├─ tests/                     # Static contract tests (no live DB required)
│  ├─ test_asta_ords_migration_contract.py
│  ├─ test_asta_adb_ords_static_contracts.py
│  └─ …
└─ scripts/
   ├─ install.sh              # 초기 설치 (uv + uv sync + 점검)
   ├─ run.sh                  # 서버 기동
   ├─ stop.sh                 # 서버 종료
   └─ oracle-ai-tool.service  # systemd unit 샘플
```

---

## 7. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 기동 시 `database unavailable` | `config.yaml` 의 `wallet_password` 또는 `dsn` 오류. 로그에서 ORA 메시지 확인. |
| `DPY-3022: named time zones are not supported` | `oracledb` thin mode 가 `TIMESTAMP WITH TIME ZONE` 미지원. 본 도구는 `CAST(SYS_EXTRACT_UTC(...) AS TIMESTAMP)` 로 우회 — 사용자 SQL 추가 시 동일 패턴 적용. |
| `Annotations: 미지원` 배지 | DB 버전이 23ai 미만이거나 `USER_ANNOTATIONS_USAGE` 뷰 없음. Annotation 기능만 비활성. |
| `DPY-4008: no bind placeholder ... :txt` | thin mode async 가 일부 DDL (COMMENT ON ...) 의 bind 를 인식 못 함. 본 도구는 SQL literal + single-quote escape 로 우회. |
| 포트 점유 | `bash scripts/stop.sh` 또는 `lsof -i :8000` 후 `kill <PID>` |
| `RUN_TEAM` 응답이 즉시 오류 | Team / Task / Tool 구성의 참조 무결성 문제 (`ORA-20051: Task X does not exist` 등). `*_ATTRIBUTES` 의 JSON 값 확인. |

---

## 8. 제한 사항 / 범위 외

PoC 단계 도구로 다음 항목은 의도적으로 구현하지 않았습니다:

- 사용자 인증 / 권한 관리
- Profile / Agent 의 신규 생성 (DDL 수준 관리는 미지원, 조회·측정만)
- 측정 결과 영속화 (세션 단위 휘발)
- 다국어 (한국어 UI 만)
- 테이블 / 컬럼의 신규 생성 / 삭제 (Comment / Annotation 수정에 한정)

운영 환경 도입 시 HTTPS 종단 (nginx / Oracle Load Balancer), 다중 사용자 인증 (OAuth / mTLS), 모니터링 등을 별도로 구성하세요.

---

## 9. 라이선스

**Apache License 2.0** — 전문은 [LICENSE](LICENSE), 저작권/고지는 [NOTICE](NOTICE) 참조.

자유롭게 사용·수정·재배포할 수 있으며, 재배포 시 LICENSE/NOTICE 와 저작권 고지를 유지하면 됩니다. 본 도구는 **PoC/데모 목적**으로 "있는 그대로(AS IS)" 제공되며, 사용으로 발생하는 어떤 손해에 대해서도 저작자는 책임지지 않습니다 (라이선스 §7 무보증 · §8 책임 제한).
