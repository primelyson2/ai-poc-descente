# 도메인 없이 Private CA 로 HTTPS 인증서 발급하기

공개 도메인 없이 **OCI Certificates 서비스의 Private CA** 로 TLS 서버 인증서를 발급해, `deploy/https` 스택(Load Balancer 443 종단)에서 쓰는 절차입니다. 실제로 `apackrsct` 테넌시 / `us-ashburn-1` / `<compartment name>` 구획에서 수행한 기록을 재사용 가능한 형태로 정리했습니다.

> 관련 문서: 배포 전체 절차는 [`Guide_Deploy_OCI.md`](Guide_Deploy_OCI.md), HTTP/HTTPS 사전 준비는 [`Prerequisites.md`](Prerequisites.md) §"프로젝트 배포(설치) 사전 준비" 참고.

---

## 1. 왜 이 방식인가

- **공개 도메인이 없어도** HTTPS 가 필요할 때(내부 데모/PoC) 쓴다.
- Private CA 는 **도메인 소유권 검증(공인 CA 의 DNS/HTTP 챌린지)이 없어서**, 원하는 내부 호스트명으로 인증서를 발급할 수 있다.
- LB 가 443 을 TLS 종단하고 인증서를 **OCID 로 참조**한다 → 우리가 확보할 최종 산출물은 **TLS 인증서 OCID**.
- 대신 브라우저가 이 CA 를 기본 신뢰하지 않으므로, 클라이언트가 **CA 루트를 신뢰 저장소에 추가**해야 경고 없이 열린다(§7).

접속은 **IP 직접(`https://<LB IP>`)이 아니라 내부 호스트명(예: `selectai.poc.local`)** 으로 한다. 브라우저는 주소창 값이 인증서 CN/SAN 과 일치해야 하며, IP SAN 지정은 까다롭기 때문(자세한 배경은 [`Prerequisites.md`](Prerequisites.md) HTTPS 절).

---

## 2. 사전 준비

| 항목 | 설명 |
|---|---|
| OCI CLI | 설치·설정(`~/.oci/config`) 완료, 대상 테넌시로 접속 가능 |
| 리전 | **LB 를 배포할 리전과 동일**해야 함 (예: `us-ashburn-1`). 인증서는 리전 리소스 |
| 구획 | CA·키·인증서를 만들 구획 (예: `<compartment name>`) |
| **Vault(KMS)** | Private CA 는 **HSM 보호 RSA 키**로 서명 → Vault + HSM RSA 키 필요 |
| IAM 권한 | CA 가 Vault 키를 쓸 수 있게 하는 정책(§4). **이게 없으면 CA 가 FAILED** |

> 아래 명령의 값들(`<COMPARTMENT_OCID>`, `<VAULT_MGMT_ENDPOINT>`, 각 OCID)은 환경마다 다르다. 이번 실제 실행값은 [부록 A](#부록-a-이번-실행에서-사용한-실제-값) 표 참고. OCID 자체는 비밀이 아니지만(인증 없이는 사용 불가) 테넌시별로 다르다.

---

## 3. 전체 흐름

```
① HSM RSA 키 생성 (Vault)         ── 키가 SOFTWARE 면 CA 생성 실패(HSM 필수)
        │
② IAM 정책 부여 (CA→키 use)        ── 없으면 CA 가 비동기로 FAILED
        │                             ("Allow service certmgmt" 은 불가 — §4)
        ▼
③ Private Root CA 생성  ──ACTIVE──►
        │
④ TLS 서버 인증서 발급 (CN/SAN=내부 호스트명)
        ▼
⑤ 인증서 OCID 확보 → deploy/https 의 certificate_ocid 로 사용
```

---

## 4. IAM 권한 — 가장 중요한 함정

Private CA 가 Vault 키로 서명하려면 **CA 리소스(리소스 주체)에게 키 사용 권한**을 줘야 한다. 여기서 흔히 막힌다.

### ✅ 되는 방법 A — 동적 그룹 (권장)
```
# 동적 그룹 매칭 규칙 — CA 리소스를 멤버로
resource.type='certificateauthority'
# 정책
Allow dynamic-group <DG_NAME> to use keys in compartment <compartment name>
```
> Identity Domains 사용 시 정책에서 `dynamic-group 'DomainName'/'<DG_NAME>'` 로 도메인 경로 참조.

### ✅ 되는 방법 B — `any-user` + 조건절 (차선책 · 동적 그룹 없이)
동적 그룹을 만들기 번거로우면 정책 한 줄의 조건절로 CA 리소스 주체를 직접 지정한다:
```
Allow any-user to use keys in compartment <compartment name> where all { request.principal.type = 'certificateauthority' }
```
키까지 좁히려면:
```
Allow any-user to use keys in compartment <compartment name> where all { request.principal.type = 'certificateauthority', target.key.id = '<HSM_KEY_OCID>' }
```
> ⚠️ **`where { request.principal.type = 'certificateauthority' }` 조건을 절대 빼지 말 것.** 빼면 아무 사용자·리소스나 키를 쓸 수 있는 보안 구멍이 된다.

두 방법은 **보안 범위가 동일**하다(둘 다 CA 리소스로만 한정). **동적 그룹(방법 A)** 을 기본으로 쓰고,
그룹 생성이 번거로우면 한 줄로 끝나는 **방법 B** 를 차선책으로 쓴다.

> 정책은 반영에 수 초~1분 걸릴 수 있다. **정책을 먼저 넣고 나서 CA 를 생성**할 것. (CA 는 생성 요청은 성공해도 키 접근 실패 시 **비동기로 FAILED** 되며, FAILED CA 는 되살릴 수 없어 삭제 후 재생성해야 한다.)

---

## 5. 단계별 절차

아래는 CLI 기준. 콘솔로 해도 동일한 개념이다.

### Step 1 — Vault 에 HSM RSA 키 생성

기존 Vault 재사용(없으면 먼저 Vault 생성). **`--protection-mode HSM` 필수** (SOFTWARE 키는 CA 생성 시 `is not backed by a hardware security module (HSM)` 오류).

```bash
oci kms management key create \
  --compartment-id <COMPARTMENT_OCID> \
  --endpoint <VAULT_MGMT_ENDPOINT> \
  --region us-ashburn-1 \
  --display-name "select-ai-private-ca-key-hsm" \
  --key-shape '{"algorithm":"RSA","length":256}' \
  --protection-mode HSM \
  --wait-for-state ENABLED
```
- `length` 은 **바이트** 단위: 256=RSA2048, 384=RSA3072, 512=RSA4096.
- `<VAULT_MGMT_ENDPOINT>` 는 Vault 의 `management-endpoint` (예: `https://<id>-management.kms.us-ashburn-1.oraclecloud.com`). `oci kms management vault list --compartment-id … --endpoint` 로 확인.

### Step 2 — IAM 정책 부여
§4 의 **방법 A 또는 B** 를 콘솔(Identity & Security → Policies / Dynamic Groups)에서 생성. 반영 대기(수 초).

### Step 3 — Private Root CA 생성

```bash
oci certs-mgmt certificate-authority create-root-ca-by-generating-config-details \
  --name "select-ai-https-root-ca" \
  --compartment-id <COMPARTMENT_OCID> \
  --kms-key-id <HSM_KEY_OCID> \
  --subject '{"commonName":"SelectAI PoC Root CA"}' \
  --signing-algorithm "SHA256_WITH_RSA" \
  --description "Private Root CA for SELECT AI PoC HTTPS (no public domain)" \
  --region us-ashburn-1 \
  --wait-for-state ACTIVE --wait-for-state FAILED
```
- 결과가 **ACTIVE** 여야 정상. **FAILED** 면 `lifecycle-details` 확인 → 대개 키 권한(§4) 문제:
  ```bash
  oci certs-mgmt certificate-authority get --certificate-authority-id <CA_OCID> \
    --region us-ashburn-1 --query "data.\"lifecycle-details\""
  # 예: "Authorization failed or requested resource not found: Key Id ocid1.key...."
  ```
- FAILED CA 정리(즉시 삭제 불가, 최소 7일 예약 삭제):
  ```bash
  oci certs-mgmt certificate-authority schedule-deletion --certificate-authority-id <CA_OCID> --region us-ashburn-1
  ```

### Step 4 — TLS 서버 인증서 발급 (도메인 없이 내부 호스트명)

```bash
oci certs-mgmt certificate create-certificate-issued-by-internal-ca \
  --name "select-ai-poc-tls" \
  --compartment-id <COMPARTMENT_OCID> \
  --certificate-profile-type "TLS_SERVER" \
  --issuer-certificate-authority-id <CA_OCID> \
  --subject '{"commonName":"selectai.poc.local"}' \
  --subject-alternative-names '[{"type":"DNS","value":"selectai.poc.local"}]' \
  --key-algorithm "RSA2048" \
  --signature-algorithm "SHA256_WITH_RSA" \
  --description "TLS server cert for SELECT AI PoC HTTPS (internal hostname)" \
  --region us-ashburn-1 \
  --wait-for-state ACTIVE --wait-for-state FAILED
```
- `create-certificate-issued-by-internal-ca` = **개인키를 OCI 가 관리**하는 인증서(LB 가 OCID 로 바로 참조 가능).
- `commonName`·SAN 의 `selectai.poc.local` 이 **실제 접속할 호스트명**. 다른 이름을 쓰려면 여기와 §7 hosts 매핑을 함께 바꾼다.

### Step 5 — OCID 확인

```bash
oci certs-mgmt certificate get --certificate-id <CERT_OCID> --region us-ashburn-1 \
  --query "data.{name:name, state:\"lifecycle-state\", profile:\"certificate-profile-type\"}"
```
`data.id` 가 **`deploy/https` 스택의 `certificate_ocid` 에 넣을 값**이다.

---

## 6. 트러블슈팅 (실제로 겪은 것)

| 증상 | 원인 / 해결 |
|---|---|
| 키 생성은 됐는데 CA 가 `... is not backed by a hardware security module (HSM)` | 키가 SOFTWARE. **`--protection-mode HSM`** 로 다시 생성 |
| 정책 저장 시 **"Service {certmgmt} does not exist"** | `Allow service certmgmt …` 는 불가. §4 방법 A(동적 그룹) 또는 B(`any-user`+조건) 사용 |
| CA 가 **FAILED**, `lifecycle-details` 에 `Authorization failed … Key Id …` | CA 가 키 쓸 권한 없음. §4 정책 넣고 **새 CA 재생성**(FAILED 는 복구 불가) |
| 브라우저 인증서 경고 | Private CA 미신뢰 or 호스트명 불일치. §7 (CA 신뢰 추가 + 호스트명 접속) |

---

## 7. 배포 연결 & 클라이언트 신뢰

### deploy/https 스택
- 변수 **`certificate_ocid`** ← Step 5 의 TLS 인증서 OCID.
- LB 가 인증서를 읽을 정책(배포 전 1회):
  ```
  Allow any-user to read certificate-bundles in compartment <compartment name> where all { request.principal.type = 'loadbalancer' }
  ```
  > 동적 그룹 방식(권장)과 이 조건절(차선책)의 선택 기준은 [`Prerequisites.md`](Prerequisites.md) 의
  > "필요 IAM 정책 (Policy) 모음" 2)번 참고. LB 는 동적 그룹 멤버 인증이 환경에 따라 다를 수 있어 이 조건절이 더 확실하다.

### 클라이언트(접속 PC)
1. **호스트명 매핑** — hosts 파일 또는 사내 DNS 에 `<LB IP>  selectai.poc.local`.
2. **CA 루트 신뢰 추가** — CA 번들 내보내 신뢰 저장소(Windows 인증서 저장소 / macOS 키체인)에 등록:
   ```bash
   oci certs-mgmt certificate-authority-bundle get --certificate-authority-id <CA_OCID> \
     --region us-ashburn-1 --query "data.\"certificate-pem\"" --raw-output > selectai-poc-ca.pem
   ```
3. `https://selectai.poc.local` 접속 → 경고 없이 열림.

---

## 8. 정리(cleanup) 주의

- KMS 키·CA 는 **즉시 삭제 불가**, `schedule-deletion` 으로 **최소 7일 예약 삭제**만 가능.
- **CA 가 사용 중인 HSM 키는 삭제하면 안 됨**(인증서 검증 깨짐).
- 데모 종료 시: 인증서 → CA → (더 이상 안 쓰면) 키 순으로 예약 삭제, LB/스택은 `Destroy`.

---

## 부록 A. 이번 실행에서 사용한 실제 값

`apackrsct` 테넌시 / `us-ashburn-1` / `<compartment name>` 구획.

| 항목 | 값 |
|---|---|
| 구획 `<compartment name>` OCID | `ocid1.compartment.oc1..aaaaaaaagl2xgcsoc3zppb6srdw5s5kzsaxts2xdp37cjkqas5rpawht76nq` |
| Vault `mdskey` 관리 엔드포인트 | `https://ejuxn42faacbc-management.kms.us-ashburn-1.oraclecloud.com` |
| **HSM 키** `select-ai-private-ca-key-hsm` | `ocid1.key.oc1.iad.ejuxn42faacbc.abuwcljtatnklma4mm65lhxtghtkalkwlkucvzkvlojl6razv4jxy4ddd7qa` |
| **Private Root CA** `select-ai-https-root-ca` | `ocid1.certificateauthority.oc1.iad.amaaaaaavsea7yianfufp6rpvgblocarg6shdfzn63lobzquu5gnvnc5rjoq` |
| **TLS 인증서** `select-ai-poc-tls` ⭐ | `ocid1.certificate.oc1.iad.amaaaaaavsea7yiaiztetw2rffm4lxewoamozyukoiiey7hsjn3ifo7l3lva` |
| 호스트명(CN/SAN) | `selectai.poc.local` |
| 적용한 키 사용 정책 | `Allow any-user to use keys in compartment <compartment name> where all { request.principal.type = 'certificateauthority' }` |

⭐ = `deploy/https` 의 `certificate_ocid` 에 넣을 값.

정리 대상(진행 중 생성): FAILED CA `select-ai-poc-root-ca`(예약 삭제 요청함), 미사용 SOFTWARE 키 `select-ai-private-ca-key`(`ocid1.key.oc1.iad.ejuxn42faacbc.abuwcljrgjfi5sskqundiwxowwwzy43i7bm77is6ntsas2tglt7ktkykdrfa`).
