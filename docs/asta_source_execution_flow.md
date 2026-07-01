# ASTA 소스코드 실행 흐름

## 1. 문서 목적

이 문서는 OADT2 ASTA(AI SQL Tuning Assistant) 화면에서 사용자가 **AI 분석 실행**을 누른 뒤 어떤 소스 파일의 어떤 함수·프로시저가 순서대로 실행되는지 설명한다.

분석 범위:

- 브라우저 UI 및 HTTP 호출
- FastAPI 인증·라우팅·비동기 ORDS proxy
- ADB ORDS endpoint
- ADB PL/SQL 메인 오케스트레이션
- ADB → DB Link → Source DB 실행 경계
- Source SQL 실행, 통계, XPLAN, SQL Tuning Advisor
- Vector 검색과 LLM SQL 재작성
- 후보 SQL 재실행과 Before/After 비교
- Markdown 결과서 생성과 조회

> 핵심 원칙: FastAPI는 ASTA SQL 튜닝을 직접 수행하지 않는다. 실제 오케스트레이션은 ADB의 `ASTA_PKG`가 담당하고, Source SQL 실행은 ADB에서 허용된 DB Link를 통해 Source DB의 `ASTA_SOURCE_PKG`가 수행한다.

---

## 2. 전체 실행 흐름

```text
브라우저
  static/js/extensions/tuning_assistant.js
    └─ POST /api/asta/analyze

FastAPI
  app/main.py
    └─ access_gate()
       └─ app/routers/asta_proxy.py
          └─ analyze()
             ├─ payload 정규화
             ├─ run_id 생성
             ├─ RUNNING 즉시 반환
             └─ BackgroundTasks
                └─ _run_ords_analyze_background()
                   └─ POST ORDS /asta/analyze

ADB ORDS
  db/ords/asta_ords_module.sql
    └─ ASTA_PKG.ANALYZE_SQL(:body_text)

ADB
  db/adb/asta_pkg.sql
    ├─ SQL Guard
    ├─ Source 연결 allowlist 조회
    ├─ 원본 SQL Evidence 수집
    ├─ SQL Tuning Advisor 상태 반영
    ├─ Vector KB 유사 사례 검색
    ├─ DBMS_CLOUD_AI SQL 재작성
    ├─ 후보 SQL Evidence 수집
    ├─ Before/After 비교
    ├─ LLM 최종 리뷰
    ├─ Markdown 결과서 생성
    ├─ Vector 사례 저장
    └─ ASTA_RUNS에 최종 결과 저장

Source DB
  db/source/asta_source_pkg.sql
    ├─ SQL 실제 실행
    ├─ V$SQL 실행 통계 수집
    ├─ DBMS_XPLAN.DISPLAY_CURSOR
    ├─ 테이블·컬럼·인덱스 통계 수집
    └─ DBMS_SCHEDULER → DBMS_SQLTUNE

브라우저
  ├─ GET /api/asta/runs/{run_id}/progress 반복
  └─ GET /api/asta/runs/{run_id}/report
```

---

## 3. FastAPI 애플리케이션 시작

파일: `app/main.py`

### 3.1 애플리케이션 초기화

```python
lifespan()
  → load_config()
  → deps.set_config(cfg)
  → db.init_pool(...)
```

주요 위치:

- `lifespan()`: `app/main.py:25`
- FastAPI 생성: `app/main.py:37`
- ASTA router 등록: `app/main.py:114`

```python
app.include_router(asta_proxy.router, prefix="/api")
```

`asta_proxy.router`의 자체 prefix가 `/asta`이므로 실제 endpoint는 다음과 같다.

```text
/api/asta/analyze
/api/asta/profiles
/api/asta/runs/{run_id}
/api/asta/runs/{run_id}/progress
/api/asta/runs/{run_id}/report
/api/asta/llm-sql-only
```

### 3.2 API 인증 및 DB 선택

모든 `/api/*` 요청은 먼저 다음 middleware를 통과한다.

```python
access_gate()
```

위치: `app/main.py:84`

처리 내용:

1. 사전공유 키 인증 여부 확인
2. 인증 cookie 검증
3. `call_next(request)`로 실제 router 호출
4. CSP 및 보안 header 추가

각 ASTA endpoint의 `Depends(current_db)`는 다음 작업을 수행한다.

- `X-Database` header 또는 기본 DB 선택
- 설정에 존재하는 DB인지 검증
- DB pool 상태 확인

---

## 4. ASTA 화면 진입

핵심 파일:

- `static/index.html`
- `static/js/extensions/app_extensions.js`
- `static/js/app.js`
- `static/js/extensions/tuning_assistant.js`

### 4.1 JavaScript 로딩 순서

`static/index.html`에서 다음 순서로 로드한다.

```text
tuning_assistant.js
app_extensions.js
app.js
```

`app_extensions.js`가 `tuning` route를 등록하고, `#/tuning` 진입 시 다음 view를 실행한다.

```javascript
window.Views.tuningAssistant()
```

정의 위치:

```text
static/js/extensions/tuning_assistant.js:691
```

### 4.2 화면 구성

`tuningAssistant()`는 다음 UI를 생성한다.

- AI Profile 선택
- 샘플 SQL 선택
- LLM 참고사항
- SQL 입력창
- AI 분석 실행 버튼
- 현재 실행 단계
- 결과서 표시 영역
- Markdown 다운로드 버튼

초기 상태는 `renderProgressStack(..., READY)`로 표시한다.

### 4.3 AI Profile 조회

화면 초기화 중 다음 함수가 실행된다.

```javascript
loadAstaProfiles()
  → fetchJson("/api/asta/profiles")
```

위치:

- `loadAstaProfiles()`: `tuning_assistant.js:1062`
- HTTP 호출: `tuning_assistant.js:1064`

FastAPI 흐름:

```text
profiles()
  → _resolve_ords_url()
  → _get_json_from_ords()
  → _filter_asta_profiles()
```

위치: `app/routers/asta_proxy.py:435`

ORDS는 다음 ADB 함수를 호출한다.

```sql
ASTA_PKG.LIST_PROFILES
```

위치: `db/ords/asta_ords_module.sql:80`

이름이 `ASTA`로 시작하고 선택 가능한 profile만 UI에 표시한다. 조회 실패 시 UI에 하드코딩된 기본 목록을 유지한다.

---

## 5. 사용자가 AI 분석 실행을 누름

이벤트 시작점:

```javascript
document.getElementById("asta-run").addEventListener("click", async () => ...)
```

위치: `static/js/extensions/tuning_assistant.js:1196`

### 5.1 요청 준비

호출 함수:

```javascript
buildBaseUrl(DEFAULT_ENDPOINT)
buildAnalyzeUrl(DEFAULT_ENDPOINT)
formatSql(sql)
```

관련 위치:

- `buildAnalyzeUrl()`: `tuning_assistant.js:588`
- `buildBaseUrl()`: `tuning_assistant.js:601`
- `fetchJson()`: `tuning_assistant.js:608`

기본 endpoint:

```text
/api/asta/analyze
```

빈 SQL이면 HTTP 요청 없이 종료한다.

### 5.2 임시 진행 표시

분석 요청 직후:

- 실행 버튼을 비활성화한다.
- 버튼 문구를 `분석중`으로 변경한다.
- 500ms 간격의 client progress timer를 시작한다.
- 서버 progress를 받기 전까지 요청 수신 및 ORDS 실행 중 상태를 임시 표시한다.

이 timer는 실제 DB progress 조회가 아니다. 실제 progress polling은 `/analyze` 응답에서 `run_id`를 받은 다음 시작한다.

### 5.3 POST payload

호출:

```http
POST /api/asta/analyze
Content-Type: application/json
```

주요 body:

```json
{
  "sql_text": "<포맷된 SQL>",
  "sql": "<포맷된 SQL>",
  "source_db_id": "DB0903_TESTDB",
  "ai_profile": "<선택 profile>",
  "llm_profile": "<선택 profile>",
  "use_llm": true,
  "run_advisor": true,
  "use_sqltune": true,
  "sqltune_time_limit": 1800,
  "tuning_context": {
    "user_notes": "<사용자 참고사항>",
    "source": "UI_OPTIONAL_TEXT"
  },
  "options": {
    "fetch_rows": 100,
    "timeout_seconds": 900,
    "sqltune_time_limit": 1800,
    "run_advisor": true,
    "use_sqltune": true,
    "run_mode": "ASYNC",
    "use_llm": true,
    "llm_profile": "<선택 profile>"
  }
}
```

위치: `tuning_assistant.js:1241-1271`

---

## 6. FastAPI 분석 요청 처리

파일: `app/routers/asta_proxy.py`

진입 함수:

```python
@router.post("/analyze")
async def analyze(...)
```

위치: `asta_proxy.py:537`

### 6.1 요청 정규화

```python
payload = await request.json()
ords_payload = _coerce_payload(payload)
```

`_coerce_payload()` 위치: `asta_proxy.py:167`

처리 내용:

- `sql`과 `sql_text` 통일
- `ai_profile`과 `llm_profile` 통일
- `fetch_rows`, `vector_top_k`, SQLTUNE 제한시간 기본값 적용
- `run_advisor`와 `use_sqltune` 통일
- `source_schema`, `source_db_link` 제거
- `source_db_id`만 전달

브라우저가 임의의 Source schema나 DB Link 이름을 지정하지 못하도록 한다. 실제 연결 정보는 ADB의 `ASTA_SOURCE_CONNECTIONS`에서 조회한다.

### 6.2 run_id 생성

```python
_new_proxy_run_id()
```

형식:

```text
OADT2-ASTA-<UUID>
```

생성한 값을 다음 두 필드에 동일하게 넣는다.

```python
ords_payload["run_id"] = run_id
ords_payload["client_run_id"] = run_id
```

### 6.3 비동기 실행 등록

FastAPI memory에 초기 실행 상태를 저장한다.

```python
_store_async_run(...)
```

그 후 background task를 등록한다.

```python
background_tasks.add_task(
    _run_ords_analyze_background,
    ...
)
```

위치: `asta_proxy.py:586`

브라우저에는 즉시 다음 형태를 반환한다.

```json
{
  "run_id": "OADT2-ASTA-...",
  "status": "RUNNING",
  "progress": [],
  "proxy": {
    "source": "FASTAPI_ASYNC_PROXY",
    "external_call": false
  }
}
```

### 6.4 BackgroundTasks에서 ORDS 호출

함수:

```python
_run_ords_analyze_background()
```

위치: `asta_proxy.py:101`

호출 관계:

```text
_run_ords_analyze_background()
  → _post_json_to_ords()
  → asyncio.to_thread(_post_json_sync)
  → _request_json_sync()
  → urllib_request.urlopen()
```

ORDS 응답 후:

```text
_annotate_proxy()
_complete_async_run()
asta_audit.write_run_index()
asta_audit.write_event()
```

FastAPI는 여기서 Source SQL 실행, XPLAN 수집, Vector 검색, LLM 재작성, SQLTUNE 또는 결과서 생성을 수행하지 않는다.

---

## 7. ORDS에서 ADB PL/SQL 호출

파일: `db/ords/asta_ords_module.sql`

ORDS module:

```text
module: asta.v1
base path: asta/
```

`POST /asta/analyze` handler의 핵심 호출:

```sql
l_response := ASTA_PKG.ANALYZE_SQL(:body_text);
```

위치: `asta_ords_module.sql:38`

ORDS는 반환된 CLOB을 2,000자 단위로 HTTP response에 출력한다.

```sql
WHILE l_offset <= NVL(DBMS_LOB.GETLENGTH(l_response), 0) LOOP
  l_chunk := DBMS_LOB.SUBSTR(l_response, 2000, l_offset);
  HTP.prn(l_chunk);
  l_offset := l_offset + 2000;
END LOOP;
```

ORDS는 분석 로직을 직접 수행하지 않는 얇은 HTTP-to-PL/SQL adapter이다.

---

## 8. ADB 메인 오케스트레이션

파일: `db/adb/asta_pkg.sql`

메인 함수:

```sql
FUNCTION analyze_sql(p_body_json IN CLOB) RETURN CLOB
```

위치: `asta_pkg.sql:536`

### 8.1 요청값 파싱

파싱 대상:

- `run_id` 또는 `client_run_id`
- `sql` 또는 `sql_text`
- `llm_profile` 또는 `ai_profile`
- `source_db_id`
- `use_llm`
- `fetch_rows`
- `vector_top_k`
- `sqltune_time_limit`
- `run_advisor` 또는 `use_sqltune`
- `tuning_context`

위치: `asta_pkg.sql:574-639`

### 8.2 ASTA_RUNS 생성

```sql
INSERT INTO asta_runs(...)
VALUES (..., 'RUNNING', ...);

COMMIT;
```

위치: `asta_pkg.sql:641-662`

분석 초기에 commit하므로 장시간 실행 중에도 다른 request가 run과 progress를 조회할 수 있다.

---

## 9. 11단계 분석 절차

### 9.1 단계 1~2: 요청 수신과 ORDS 전달

```sql
record_progress(..., 1, 'REQUEST_RECEIVED', ..., 'DONE');
record_progress(..., 2, 'ORDS_DISPATCH', ..., 'DONE');
```

위치: `asta_pkg.sql:581-582`

`record_progress()`는 `ASTA_RUN_PROGRESS`에 상태를 저장한다.

정의 위치: `asta_pkg.sql:125`

이 procedure는 autonomous transaction을 사용하므로 메인 분석 transaction이 끝나기 전에도 progress를 조회할 수 있다.

### 9.2 단계 3: SQL Guard

호출:

```sql
asta_sql_guard_pkg.assert_safe_select(l_sql);
```

위치: `asta_pkg.sql:665`

구현:

- 파일: `db/adb/asta_sql_guard_pkg.sql`
- 함수: `assert_safe_select()`
- 위치: `asta_sql_guard_pkg.sql:112`

정책:

- `SELECT` 또는 `WITH` 단일문만 허용
- DML 차단
- DDL 차단
- PL/SQL 차단
- 다중 statement 차단
- 위험한 terminator 차단

LLM 후보 SQL도 별도로 같은 정책을 통과해야 한다.

### 9.3 단계 4: Source 연결 조회

```sql
asta_source_bridge_pkg.get_connection_json(l_source_db_id)
```

위치: `asta_pkg.sql:669`

내부 `resolve_connection()`이 `ASTA_SOURCE_CONNECTIONS`에서 다음 값을 조회한다.

- `source_db_id`
- `db_link_name`
- `source_schema`
- `enabled_yn`

연결은 사용자 payload가 아니라 ADB allowlist가 결정한다.

### 9.4 단계 4: 원본 SQL Evidence

```sql
asta_source_bridge_pkg.run_source_evidence(
  p_source_db_id     => l_source_db_id,
  p_sql              => l_sql,
  p_run_id           => l_run_id,
  p_fetch_rows       => l_fetch_rows,
  p_repeat_policy    => 'AUTO',
  p_run_advisor      => l_run_advisor,
  p_sqltune_time_sec => l_sqltune_time_limit
)
```

위치: `asta_pkg.sql:702-710`

### 9.5 단계 5: SQL Tuning Advisor 상태

Source Evidence JSON의 Advisor 상태를 읽어 progress에 반영한다.

```sql
advisor_progress_status(l_source_json)
advisor_progress_detail(l_source_json, l_run_advisor)
```

위치: `asta_pkg.sql:717-724`

별도의 Advisor 재실행이 아니라 Source에서 이미 수행된 Advisor 결과를 진행 단계로 기록하는 부분이다.

### 9.6 단계 6: Vector KB 검색

```sql
asta_vector_pkg.search_similar_cases(l_sql, l_vector_top_k)
```

위치: `asta_pkg.sql:727`

구현:

- 파일: `db/adb/asta_vector_pkg.sql`
- 함수: `search_similar_cases()`
- 위치: `asta_vector_pkg.sql:137`

현재 SQL과 과거 ASTA 튜닝 사례를 비교해 LLM prompt에 넣을 유사 사례를 반환한다.

### 9.7 단계 7: LLM SQL 재작성

```sql
asta_llm_pkg.generate_tuning(...)
```

위치: `asta_pkg.sql:731-738`

구현:

- 파일: `db/adb/asta_llm_pkg.sql`
- 함수: `generate_tuning()`
- 위치: `asta_llm_pkg.sql:368`

내부 흐름:

```text
assert_safe_select(원본 SQL)
  → build_tuning_prompt()
  → DBMS_CLOUD_AI.GENERATE(action => 'chat')
  → asta_sql_guard_pkg.extract_candidate_sql()
  → 후보 SQL 안전성 검사
```

후보가 없거나 원본 SQL과 동일하면 다음 보조 경로를 시도한다.

```sql
asta_llm_pkg.generate_sql_only_tuning(...)
```

위치: `asta_pkg.sql:759`

### 9.8 단계 8: 후보 SQL Evidence

안전한 후보가 있으면 원본과 동일한 Source 경로로 실제 실행한다.

```sql
asta_source_bridge_pkg.run_source_evidence(
  p_sql          => l_tuned_sql,
  p_run_id       => l_run_id || '-TUNED',
  p_run_advisor  => 'N'
)
```

위치: `asta_pkg.sql:783-791`

후보 SQL 실행이 실패하면:

```text
LLM 후보 거절
  → 원본 SQL 유지
  → 원본 SQL을 <run_id>-SAFE로 재실행
```

관련 위치: `asta_pkg.sql:793-811`

### 9.9 단계 9: Before/After 비교

```sql
build_comparison_json(l_source_json, l_after_json)
```

위치: `asta_pkg.sql:820`

주요 비교값:

- row count
- output rows 일치 여부
- buffer gets
- disk reads
- elapsed time
- 전후 실행 상태

그 후 LLM 최종 리뷰를 수행한다.

```sql
asta_llm_pkg.final_review(...)
```

위치: `asta_pkg.sql:834-838`

LLM은 evidence를 변경하지 않고 Before/After 결과를 설명하고 보고서 초안을 생성한다.

### 9.10 단계 10: 최종 결과서

```sql
asta_report_pkg.build_report(...)
```

위치: `asta_pkg.sql:846-858`

결과서 구성:

- 결론
- 원본 SQL
- 후보 SQL
- Before/After 수치
- SQL Tuning Advisor 결과
- 사용자 참고사항
- 원본 XPLAN
- 후보 SQL XPLAN
- 테이블 및 컬럼 통계
- 인덱스 정보

XPLAN 및 오브젝트 통계는 LLM이 작성한 값이 아니라 Source DB에서 수집한 artifact를 직접 붙인다.

### 9.11 단계 11: Vector 사례 저장

```sql
asta_vector_pkg.save_case(...)
```

위치: `asta_pkg.sql:862-868`

저장 정보:

- run_id
- 원본 SQL
- 후보 SQL
- Markdown 결과서
- LLM metadata

관련 테이블:

```text
ASTA_TUNING_CASES
ASTA_TUNING_CASE_CHUNKS
```

### 9.12 최종 JSON 및 ASTA_RUNS 갱신

```sql
asta_report_pkg.build_response_json(...)
```

위치: `asta_pkg.sql:872-885`

그 후:

```sql
UPDATE asta_runs
SET status = l_status,
    tuned_sql = l_tuned_sql,
    completed_at = SYSTIMESTAMP,
    detailed_report_md = l_report_markdown,
    response_json = l_response_json
WHERE run_id = l_run_id;

COMMIT;
```

위치: `asta_pkg.sql:887-894`

예외가 발생해도 실패 상태의 결과서와 response JSON을 생성해 `ASTA_RUNS`에 저장한다.

---

## 10. ADB → Source DB 실행 경계

파일: `db/adb/asta_source_bridge_pkg.sql`

함수:

```sql
run_source_evidence()
```

위치: `asta_source_bridge_pkg.sql:150`

### 10.1 DB Link procedure 호출

```sql
BEGIN
  <source_schema>.asta_source_pkg.run_evidence_store_proc@<db_link>(...);
END;
```

동적 호출문 생성 위치: `asta_source_bridge_pkg.sql:185-188`

실행 위치: `asta_source_bridge_pkg.sql:194-201`

호출 구조:

```text
ADB ASTA_SOURCE_BRIDGE_PKG
  → 허용된 DB Link
    → Source DB ASTA_SOURCE_PKG.RUN_EVIDENCE_STORE_PROC
```

FastAPI나 ADB Python pool이 Source DB에 직접 연결하지 않는다.

### 10.2 Source 결과 chunk 회수

Source의 결과 JSON은 대용량 CLOB이므로 DB Link OUT CLOB로 직접 반환하지 않는다.

```text
Source ASTA_SOURCE_RESULTS에 저장
  → GET_RESULT_CHUNK@DBLINK 반복 호출
  → ADB에서 CLOB 재조립
```

ADB 호출:

```sql
asta_source_pkg.get_result_chunk@<db_link>(...)
```

위치: `asta_source_bridge_pkg.sql:207-222`

한 번에 8,000자씩 읽는다.

Bridge는 commit 또는 rollback하지 않는다. Source helper의 autonomous transaction이 Source 결과 저장을 담당한다.

---

## 11. Source DB Evidence 수집

파일: `db/source/asta_source_pkg.sql`

진입 관계:

```text
run_evidence_store_proc()
  → run_evidence_store_vc()
    → run_evidence()
```

### 11.1 DB Link wrapper

- `run_evidence_store_proc()`: `asta_source_pkg.sql:1029`
- `run_evidence_store_vc()`: `asta_source_pkg.sql:904`
- autonomous transaction: `asta_source_pkg.sql:912`

### 11.2 실제 Evidence 함수

```sql
FUNCTION run_evidence(...) RETURN CLOB
```

위치: `asta_source_pkg.sql:730`

처리 순서:

1. `assert_safe_select()`로 Source 측 재검증
2. fetch rows 및 repeat policy 정규화
3. `build_exec_sql()`로 제한된 실행 SQL 생성
4. `EXECUTE IMMEDIATE`로 실제 SQL 실행
5. run marker로 cursor 검색
6. 실행 통계 수집
7. `DBMS_XPLAN.DISPLAY_CURSOR` 실행
8. plan object 기반 메타데이터 수집
9. 선택적 Advisor 처리
10. Evidence JSON 생성

### 11.3 실제 SQL 실행

```sql
FOR i IN 1..l_repeats LOOP
  EXECUTE IMMEDIATE l_exec_sql INTO l_row_count;
END LOOP;
```

위치: `asta_source_pkg.sql:785-787`

`build_exec_sql()`은 다음 목적을 가진다.

- `gather_plan_statistics` 사용
- ASTA run marker 삽입
- 조회 행 제한
- 실제 실행계획과 실행 통계 수집

### 11.4 Cursor와 실행 통계

```sql
find_cursor(...)
collect_metrics(...)
```

위치:

- `find_cursor()`: `asta_source_pkg.sql:398`
- 호출: `asta_source_pkg.sql:797`
- `collect_metrics()`: `asta_source_pkg.sql:429`
- 호출: `asta_source_pkg.sql:801-804`

수집 항목:

- SQL_ID
- child cursor
- plan hash value
- output rows
- buffer gets
- disk reads
- elapsed time

주요 통계 source:

```text
V$SQL_PLAN_STATISTICS_ALL
```

### 11.5 실제 XPLAN 수집

```sql
collect_xplan(l_sql_id, l_child_number)
```

내부 호출:

```sql
DBMS_XPLAN.DISPLAY_CURSOR(...)
```

위치:

- 정의: `asta_source_pkg.sql:466`
- 호출: `asta_source_pkg.sql:809`

따라서 결과서의 XPLAN 원문은 LLM 생성 텍스트가 아니다.

### 11.6 오브젝트 메타데이터

```sql
collect_object_info(l_sql_id, l_child_number)
```

위치:

- 정의: `asta_source_pkg.sql:504`
- 호출: `asta_source_pkg.sql:810`

수집 대상:

- table statistics
- column statistics
- indexes
- index columns

---

## 12. SQL Tuning Advisor의 실제 운영 경로

DB Link 기반 운영 경로에서는 `run_evidence_store_vc()`가 기본 Evidence를 먼저 수집하고 Advisor를 별도의 Scheduler job으로 수행한다.

```text
RUN_EVIDENCE_STORE_PROC()
  → RUN_EVIDENCE_STORE_VC()
     ├─ RUN_EVIDENCE(p_run_advisor => 'N')
     │  ├─ SQL 실행
     │  ├─ metrics
     │  ├─ XPLAN
     │  └─ object metadata
     │
     └─ Advisor 요청 시
        DBMS_SCHEDULER.CREATE_JOB()
          → RUN_ADVISOR_JOB()
             → RUN_ADVISOR_OPT()
                ├─ DBMS_SQLTUNE.CREATE_TUNING_TASK()
                ├─ DBMS_SQLTUNE.EXECUTE_TUNING_TASK()
                ├─ DBMS_SQLTUNE.REPORT_TUNING_TASK()
                └─ DBMS_SQLTUNE.DROP_TUNING_TASK()
```

관련 위치:

- 기본 Evidence 호출: `asta_source_pkg.sql:924-931`
- Scheduler 생성 및 polling: `asta_source_pkg.sql:958-990`
- `run_advisor_job()`: `asta_source_pkg.sql:695`
- `run_advisor_opt()`: `asta_source_pkg.sql:648`

restricted login이면 Source 직접접속 fallback을 시도하지 않는다. Advisor 상태를 `FAILED`로 기록하고 DBA가 정상 login을 허용한 후 재실행하도록 actionable message를 남긴다.

---

## 13. Progress 조회

### 13.1 ADB progress 저장

```sql
ASTA_PKG.RECORD_PROGRESS()
```

위치: `db/adb/asta_pkg.sql:125`

`PRAGMA AUTONOMOUS_TRANSACTION`을 사용하므로 장시간 `ANALYZE_SQL()` 실행 중에도 별도 HTTP request가 진행 상태를 읽을 수 있다.

단계:

1. `REQUEST_RECEIVED`
2. `ORDS_DISPATCH`
3. `SQL_GUARD`
4. `BEFORE_EVIDENCE`
5. `SQL_TUNING_ADVISOR`
6. `VECTOR_KB`
7. `LLM_REWRITE`
8. `AFTER_EVIDENCE`
9. `LLM_FINAL_REVIEW`
10. `FINAL_REPORT`
11. `VECTOR_SAVE`

### 13.2 브라우저 polling

함수:

```javascript
pollRunProgress(baseUrl, runId, progressTarget, resultTarget)
```

위치: `tuning_assistant.js:663`

1초 간격으로 다음 endpoint를 호출한다.

```http
GET /api/asta/runs/{run_id}/progress
```

최대 반복 횟수는 2,400회이다.

### 13.3 FastAPI progress 조회

```python
get_run_progress()
  → _audited_run_lookup(run_id, database, "progress", "progress")
```

위치:

- `get_run_progress()`: `asta_proxy.py:609`
- `_audited_run_lookup()`: `asta_proxy.py:364`

조회 우선순위:

1. FastAPI `ASYNC_RUNS` memory
2. ADB ORDS progress endpoint
3. ORDS가 명시적으로 `NOT_FOUND`를 반환하면 기존 local snapshot

ORDS 통신 자체가 실패하면 local snapshot으로 자동 전환하지 않고 오류를 다시 발생시킨다.

### 13.4 ORDS 및 ADB progress 조회

ORDS:

```sql
ASTA_PKG.GET_PROGRESS(:run_id)
```

위치: `asta_ords_module.sql:164`

ADB:

```sql
ASTA_PKG.GET_PROGRESS()
  → ASTA_RUNS 조회
  → BUILD_PROGRESS_ARRAY_JSON()
  → ASTA_RUN_PROGRESS 조회
```

위치: `asta_pkg.sql:1031`

Progress 조회는 Source DB를 다시 호출하지 않는다.

---

## 14. 최종 결과서 조회

브라우저의 progress 상태가 `COMPLETED` 또는 `DONE`이면 다음 함수가 실행된다.

```javascript
fetchReport(baseUrl, runId)
```

위치: `tuning_assistant.js:639`

요청:

```http
GET /api/asta/runs/{run_id}/report
```

FastAPI:

```python
get_run_report()
  → _audited_run_lookup(..., "report")
```

위치: `asta_proxy.py:615`

ORDS:

```sql
ASTA_PKG.GET_REPORT(:run_id)
```

위치: `asta_ords_module.sql:206`

ADB:

```sql
ASTA_PKG.GET_REPORT()
  → ASTA_RUNS.DETAILED_REPORT_MD 조회
```

위치: `asta_pkg.sql:1078`

브라우저는 `renderResult()`로 Markdown 결과를 표시하고 다운로드 상태를 저장한다.

다운로드 파일 형식:

```text
asta_tuning_report_<timestamp>_<run_id>.md
```

---

## 15. Run 조회

```http
GET /api/asta/runs/{run_id}
```

호출 관계:

```text
FastAPI get_run()
  → ORDS GET runs/:run_id
    → ASTA_PKG.GET_RUN(:run_id)
      → ASTA_RUNS.RESPONSE_JSON
```

위치:

- FastAPI: `asta_proxy.py:603`
- ORDS: `asta_ords_module.sql:122`
- ADB: `asta_pkg.sql:996`

Source DB를 다시 호출하지 않고 저장된 최종 response JSON을 반환한다.

---

## 16. Local fallback과 Source 직접접속 정책

FastAPI 조회 fallback은 `_audited_run_lookup()`에 존재한다.

```text
FastAPI memory
  → ADB ORDS
  → ORDS의 명시적 NOT_FOUND이면 local final snapshot
```

현재 일반 ASTA analyze 경로에는 Source DB 직접접속 fallback이 없다.

`app/asta_source_direct.py`는 차단 shim이다.

```python
should_attempt_source_direct()      # 항상 False
apply_source_direct_fallback()      # RuntimeError
apply_source_direct_advisor_repair() # RuntimeError
```

따라서 현재 Source 실행의 유효한 경로는 다음뿐이다.

```text
ADB ASTA_SOURCE_BRIDGE_PKG
  → 허용된 DB Link
    → Source ASTA_SOURCE_PKG
```

---

## 17. SQL-only LLM 숨김 경로

UI에서 `Ctrl+Alt+L`을 사용하면 SQL-only LLM 버튼을 표시할 수 있다.

요청:

```http
POST /api/asta/llm-sql-only
```

FastAPI 함수:

```python
llm_sql_only()
```

위치: `app/routers/asta_proxy.py:445`

이 경로는 선택된 ADB pool에서 다음을 직접 수행한다.

```sql
DBMS_CLOUD_AI.GENERATE(action => 'chat')
```

다음 ASTA 기능을 우회한다.

- Source DB Evidence
- SQL Tuning Advisor
- Vector 검색
- 후보 SQL 실제 실행
- Before/After 비교
- 정식 ASTA 결과서 생성

따라서 일반 `AI 분석 실행` 경로와 별개인 디버그·비교 기능이다.

---

## 18. 프런트엔드 상태 처리 주의점

현재 `pollRunProgress()`는 다음 상태에서 종료한다.

```javascript
["COMPLETED", "DONE", "FAILED"]
```

위치: `tuning_assistant.js:671-674`

`FAILED`이면 결과서를 조회하지 않고 progress를 반환한다. 그러나 상위 실행 handler는 반환된 progress 상태를 재검사하지 않고 다음 성공 처리를 수행할 수 있다.

```javascript
runButton.textContent = "완료";
completedOk = true;
Toast.show("ASTA 분석이 완료되었습니다.");
```

위치: `tuning_assistant.js:1299-1301`

따라서 서버가 `FAILED`를 반환해도 UI가 완료 toast를 표시할 가능성이 있다.

추가 주의점:

- polling 종료 상태에 `ERROR`가 없다.
- 서버 최종 상태가 `ERROR`이면 즉시 종료되지 않을 수 있다.
- 최초 500ms progress timer는 실제 서버 progress가 아니라 client placeholder이다.
- 2,400초 제한 외에 각 HTTP 요청 소요시간이 별도로 추가된다.

---

## 19. 파일별 역할

| 계층 | 파일 | 주요 역할 |
|---|---|---|
| UI | `static/js/extensions/tuning_assistant.js` | 화면, analyze 요청, progress polling, report 표시·다운로드 |
| FastAPI 시작 | `app/main.py` | 설정, 인증 middleware, router 등록, static serving |
| FastAPI ASTA | `app/routers/asta_proxy.py` | payload 정규화, async 상태, ORDS proxy, progress/report 조회 |
| Audit | `app/asta_audit.py` | request event, run index, 호환 snapshot |
| ORDS | `db/ords/asta_ords_module.sql` | HTTP endpoint와 ADB package 연결 |
| ADB Main | `db/adb/asta_pkg.sql` | 전체 11단계 오케스트레이션 |
| SQL Guard | `db/adb/asta_sql_guard_pkg.sql` | SELECT/WITH 단일문 검증, 후보 SQL 추출·검증 |
| Source Bridge | `db/adb/asta_source_bridge_pkg.sql` | allowlist 조회, DB Link Source 호출, chunk 회수 |
| Source Runtime | `db/source/asta_source_pkg.sql` | SQL 실행, metrics, XPLAN, object stats, SQLTUNE |
| Vector | `db/adb/asta_vector_pkg.sql` | 유사 사례 검색 및 결과 저장 |
| LLM | `db/adb/asta_llm_pkg.sql` | prompt, DBMS_CLOUD_AI, 후보 SQL, final review |
| Report | `db/adb/asta_report_pkg.sql` | Markdown 결과서 및 API response JSON 생성 |

---

## 20. 소스 읽기 추천 순서

1. UI 버튼 handler  
   `static/js/extensions/tuning_assistant.js:1196`

2. FastAPI analyze endpoint  
   `app/routers/asta_proxy.py:537`

3. ORDS analyze mapping  
   `db/ords/asta_ords_module.sql:21-61`

4. ADB 전체 workflow  
   `db/adb/asta_pkg.sql:536`

5. ADB → Source DB Link 경계  
   `db/adb/asta_source_bridge_pkg.sql:150`

6. Source 실제 SQL 실행  
   `db/source/asta_source_pkg.sql:730`

7. Source store 및 Advisor Scheduler  
   `db/source/asta_source_pkg.sql:904`

8. LLM 후보 생성  
   `db/adb/asta_llm_pkg.sql:368`

9. 결과서 생성  
   `db/adb/asta_report_pkg.sql`

10. Progress polling  
    `tuning_assistant.js:663` → `asta_proxy.py:609` → `ASTA_PKG.GET_PROGRESS()`

---

## 21. 최종 요약

```text
FastAPI는 요청을 중계하고 비동기 상태를 관리한다.
ADB ASTA_PKG가 전체 분석 흐름을 제어한다.
Source ASTA_SOURCE_PKG가 SQL을 실제 실행한다.
ADB ASTA_LLM_PKG가 LLM 후보 SQL과 최종 리뷰를 만든다.
ADB ASTA_REPORT_PKG가 실제 Evidence와 XPLAN을 조합해 결과서를 만든다.
```

가장 중요한 실행 경계:

```text
Browser
  → FastAPI same-origin proxy
    → ADB ORDS
      → ADB ASTA_PKG
        → ADB Source Bridge
          → DB Link
            → Source ASTA_SOURCE_PKG
```

Source DB 직접접속 fallback은 사용하지 않는다. 원본 및 후보 SQL의 실행 결과, XPLAN, 통계가 최종 판단의 기준이며 LLM 설명이나 사용자 참고사항과 충돌할 경우 실제 Evidence가 우선한다.
