# AI SQL Tuning Assistant 사용자·운영 매뉴얼

최종 업데이트: 2026-06-26

## 1. 개요

AI SQL Tuning Assistant(ASTA)는 OADT2에 독립 extension으로 붙어 있는 SQL 튜닝 결과서 화면입니다. 사용자는 SQL과 AI Profile을 선택하면 되고, Source DB나 ORDS endpoint는 화면에서 직접 선택하지 않습니다.

현재 실행 모델:

```text
OADT2 브라우저
  → OADT2 FastAPI same-origin proxy /api/asta/*
  → ADB ORDS module asta.v1
  → ADB ASTA_PKG / 보조 PL/SQL packages
  → Source BaseDB ASTA_SOURCE_PKG via allowlisted DB Link
```

핵심 원칙:

```text
- FastAPI는 ORDS_PROXY_ONLY 역할입니다.
- SQL 실행/XPLAN/metrics/SQLTUNE/Vector/LLM/report canonical 생성은 ADB PL/SQL/ORDS에서 수행합니다.
- Source evidence는 ADB → DB Link → Source helper package 경로로 수집합니다.
- Python에서 Source DB 직접 접속, SSH tunnel, subprocess source runtime 실행은 production path에서 금지합니다.
- DB Link 경로에서 불가능한 단계는 FAILED/SKIPPED로 명확히 표시하고 직접 우회하지 않습니다.
```

상세 내부 구조와 순서도는 다음 문서를 봅니다.

```text
docs/OADT2_ASTA_ARCHITECTURE.md
```

## 2. 화면 사용법

1. 좌측 메뉴에서 **AI SQL Tuning Assistant**를 엽니다.
2. 필요하면 좌상단 `☰` 버튼으로 메뉴를 접어 화면 폭을 확보합니다.
3. **AI Profile**에서 사용할 `ASTA*` profile을 선택합니다.
4. 샘플 SQL을 선택하거나 SQL 입력창에 직접 SQL을 붙여넣습니다.
5. 필요 시 SQL Tuning Advisor 옵션을 켭니다.
   - Advisor는 시간이 오래 걸릴 수 있으므로 기본은 꺼져 있을 수 있습니다.
   - 켜면 backend payload에 `run_advisor=true` / `use_sqltune=true`가 전달됩니다.
6. **튜닝보고서 작성**을 누릅니다.
7. 수행 이력 11단계가 표시됩니다.
8. 완료되면 Markdown 결과서가 표시되고, **보고서 다운로드** 버튼으로 `.md` 파일을 저장할 수 있습니다.
9. 분석 완료 후 **신규 분석** 버튼으로 입력/결과를 초기화할 수 있습니다.

## 3. 수행 이력 11단계

UI와 ADB progress contract는 다음 단계를 기준으로 합니다.

| Seq | Code | 표시명 | 수행 위치 |
|---:|---|---|---|
| 1 | `REQUEST_RECEIVED` | 요청 수신 | ADB `ASTA_PKG` |
| 2 | `ORDS_DISPATCH` | ADB ORDS 분석 호출 | ADB `ASTA_PKG` |
| 3 | `SQL_GUARD` | SQL 안전성 검사 | `ASTA_SQL_GUARD_PKG` |
| 4 | `BEFORE_EVIDENCE` | 원본 SQL 분석: 원본 SQL/XPLAN/metrics | Source `ASTA_SOURCE_PKG` via DB Link |
| 5 | `SQL_TUNING_ADVISOR` | Tuning Advisor 수행 | Source `DBMS_SQLTUNE` via helper |
| 6 | `VECTOR_KB` | ADB Vector KB 유사 결과서 조회 | `ASTA_VECTOR_PKG` |
| 7 | `LLM_REWRITE` | AI 1차 튜닝: 분석결과 + Vector 사례 참조 | `ASTA_LLM_PKG` + `DBMS_CLOUD_AI` |
| 8 | `AFTER_EVIDENCE` | 튜닝 SQL 분석: 튜닝 SQL 재수행/비교 | Source `ASTA_SOURCE_PKG` via DB Link |
| 9 | `LLM_FINAL_REVIEW` | AI Before/After 정리 | `ASTA_LLM_PKG` + `DBMS_CLOUD_AI` |
| 10 | `FINAL_REPORT` | 최종 보고서 생성 | `ASTA_REPORT_PKG` |
| 11 | `VECTOR_SAVE` | ADB Vector KB 결과서 저장 | `ASTA_VECTOR_PKG` |

표시 원칙:

```text
- 실제 backend progress를 기준으로 표시합니다.
- 실행하지 않은 단계는 생략하지 않고 SKIPPED/FAILED reason을 표시합니다.
- 클라이언트 타이머로 가짜 완료를 만들지 않습니다.
```

## 4. 결과서 품질 기준

결과서는 다음 순서를 기준으로 합니다.

```text
# AI SQL Tuning Assistant Report
## 튜닝 결과
### Before/After 핵심 비교
## 실행 메타데이터
## 단계별 수행 체크
## 원본 SQL
## Source 실행 Evidence 요약
## Oracle SQL Tuning Advisor 요약
## 튜닝 SQL
## 튜닝 후 Source 실행 Evidence 요약
## Vector 유사 사례 요약
## DBA 검토사항
```

중요 정책:

```text
- SQL Tuning Advisor 원문은 raw dump로 붙이지 않고 핵심 요약으로 표시합니다.
- LLM에는 Source evidence, SQLTUNE, Vector 사례, before/after comparison을 evidence package로 전달합니다.
- DDL, SQL Profile, 통계 변경은 자동 적용하지 않고 DBA 검토사항으로만 제시합니다.
- Disk Reads가 있으면 elapsed time은 I/O 영향으로 흔들릴 수 있습니다.
- 특히 OLTP/짧은 SQL은 elapsed보다 Buffer Gets/consistent gets 감소를 우선 판단합니다.
```

## 5. 운영 endpoint

브라우저는 OADT2 same-origin endpoint만 호출합니다.

| Method | OADT2 Path | 설명 |
|---|---|---|
| `GET` | `/api/asta/profiles` | ADB ORDS `ASTA_PKG.LIST_PROFILES` proxy |
| `POST` | `/api/asta/analyze` | ADB ORDS `ASTA_PKG.ANALYZE_SQL` proxy |
| `GET` | `/api/asta/runs/{run_id}` | ADB ORDS `ASTA_PKG.GET_RUN` proxy |
| `GET` | `/api/asta/runs/{run_id}/progress` | ADB ORDS `ASTA_PKG.GET_PROGRESS` proxy |
| `GET` | `/api/asta/runs/{run_id}/report` | ADB ORDS `ASTA_PKG.GET_REPORT` proxy |

FastAPI는 `config.yaml`의 DB별 `asta.ords_base_url`을 사용합니다.

예시:

```yaml
databases:
  - name: devdoADB
    asta:
      ords_base_url: "https://<adb-ords-host>/ords/asta"
      analyze_path: "/analyze"
      profiles_path: "/profiles"
      timeout_seconds: 2100
```

## 6. 내부 package/파일 위치

| 영역 | 파일 |
|---|---|
| FastAPI thin proxy | `app/routers/asta_proxy.py` |
| UI extension | `static/js/extensions/tuning_assistant.js` |
| ORDS module | `db/ords/asta_ords_module.sql` |
| Main ADB orchestration | `db/adb/asta_pkg.sql` |
| SQL guard | `db/adb/asta_sql_guard_pkg.sql` |
| Source bridge | `db/adb/asta_source_bridge_pkg.sql` |
| Vector KB facade | `db/adb/asta_vector_pkg.sql` |
| DBMS_CLOUD_AI orchestration | `db/adb/asta_llm_pkg.sql` |
| Report builder | `db/adb/asta_report_pkg.sql` |
| Source BaseDB helper | `db/source/asta_source_pkg.sql` |
| Repository DDL | `db/asta/*.sql` |
| 배포 SQL | `db/deploy/*.sql` |

## 7. Source DB 정책

화면에서는 Source DB를 직접 고르지 않습니다. 기본 source id는 다음과 같습니다.

```json
{
  "source_db_id": "DB0903_TESTDB"
}
```

ADB의 `ASTA_SOURCE_CONNECTIONS`에서 `source_db_id`에 해당하는 DB Link와 Source schema를 조회합니다.

```text
source_db_id → db_link_name + source_schema
```

Source SQL execution은 Source BaseDB에 설치된 `ASTA_SOURCE_PKG`가 수행합니다.

## 8. 검증 명령

정적/계약 테스트:

```bash
cd /home/ubuntu/descente_poc_ui/ai-poc-descente-main
node --check static/js/extensions/tuning_assistant.js
uv run python -m py_compile app/routers/asta_proxy.py
uv run --with pytest pytest \
  tests/test_asta_proxy.py \
  tests/test_asta_adb_ords_static_contracts.py \
  tests/test_asta_ords_migration_contract.py \
  tests/test_tuning_assistant_static.py \
  -q
```

Profile proxy 확인:

```bash
curl -sS http://127.0.0.1:8000/api/asta/profiles | python3 -m json.tool
```

Analyze smoke 예시:

```bash
curl -sS http://127.0.0.1:8000/api/asta/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "sql":"select /* smoke */ 1 from dual",
    "llm_profile":"ASTA_GROK_REASONING_PROFILE",
    "use_llm":false,
    "run_advisor":false,
    "fetch_rows":20
  }' | python3 -m json.tool
```

## 9. 장애 대응

| 증상 | 확인 사항 |
|---|---|
| Profile이 안 보임 | `config.yaml`의 `asta.ords_base_url`, ORDS `/profiles`, `USER_CLOUD_AI_PROFILES`의 `ASTA%` profile 확인 |
| ORDS unavailable | FastAPI 오류 detail의 ORDS URL/HTTP status 확인. ORDS module publish 상태 확인 |
| SQL Guard 실패 | SELECT/WITH 단일문인지, DML/DDL/PLSQL keyword가 포함됐는지 확인 |
| Source evidence 실패 | `ASTA_SOURCE_CONNECTIONS`, DB Link, Source `ASTA_SOURCE_PKG` compile/grant 상태 확인 |
| SQL Tuning Advisor FAILED | Source DB restricted session, `DBMS_SQLTUNE` 권한, Tuning Pack/DBA 정책 확인 |
| Vector KB NOT_CONFIGURED | `ASTA_TUNING_CASES`, `ASTA_TUNING_CASE_CHUNKS` 설치 여부 확인 |
| LLM_REWRITE SKIPPED | `use_llm=false`인지, ASTA profile이 유효한지 확인 |
| LLM candidate 실패 | raw artifact의 `candidate_error` 확인. 보고서는 실질 개선 없음/후보 실패로 표시될 수 있음 |
| 결과서가 비어 있음 | `ASTA_RUNS.DETAILED_REPORT_MD`, ORDS `/runs/:id/report` 확인 |
| 수행 이력 누락 | `ASTA_RUN_PROGRESS`에 11단계 row가 기록됐는지 확인 |

## 10. 보안 주의

```text
- DB password, credential secret, wallet, private key는 문서/화면/로그에 노출하지 않습니다.
- Telegram 등 외부 채널에는 raw 내부 오류/credential을 붙이지 않고 요약합니다.
- DDL/SQL Profile/statistics 변경은 ASTA가 자동 적용하지 않습니다.
- DBA 검토가 필요한 권고는 보고서에 advisory로만 표시합니다.
```
