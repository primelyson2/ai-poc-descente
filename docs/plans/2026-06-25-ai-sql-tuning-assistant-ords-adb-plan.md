# AI SQL Tuning Assistant Current Architecture Plan

최종 업데이트: 2026-06-25

> **[SUPERSEDED — 2026-06-26]** 이 문서는 Python-local ASTA 실행 구조를 기술한 역사적 기록입니다.  
> 현행 아키텍처는 **ADB ORDS/PL/SQL-first** 이며 `docs/plans/2026-06-26-oadt2-asta-adb-ords-migration-workplan.md` 와 `docs/AI_SQL_TUNING_ASSISTANT_MANUAL.md` 를 참조하십시오.  
> Python/FastAPI 는 same-origin thin proxy 역할만 하며 SQL 실행·XPLAN·Vector·LLM·SQLTUNE·보고서 생성을 수행하지 않습니다.

> ~~이 문서는 초기 ORDS/ADB 직접 호출 계획을 대체하는 현행 구조 문서입니다. 현재 OADT2는 브라우저에서 ORDS를 직접 호출하지 않고, same-origin ASTA proxy를 통해 Select AI Demo의 canonical Python ASTA runtime을 사용합니다.~~

## 1. 현재 목표

OADT2의 `AI SQL Tuning Assistant` 화면은 사용자가 SQL과 ASTA profile만 선택하면, 앱 내부 로컬 ASTA workflow의 상세 결과서를 받아 보여주는 UI입니다.

현재 핵심 목표:

- OADT2 UI와 ASTA 실행 엔진을 분리한다.
- 브라우저 CORS/endpoint/source 선택 복잡도를 숨긴다.
- Select AI Demo와 동일한 상세 결과서 품질을 유지한다.
- BaseDB 실제 XPLAN/evidence를 사용한다.
- 모바일에서 SQL 입력과 수행 이력 흐름을 자연스럽게 유지한다.

## 2. 현행 아키텍처

```text
[Browser / OADT2]
  static/js/extensions/tuning_assistant.js
  │
  │ same-origin JSON
  ▼
[OADT2 FastAPI]
  app/routers/asta_proxy.py
  ├─ POST /api/asta/analyze
  └─ GET  /api/asta/profiles
  │
  │ server-side HTTP/SSE
  ▼
[Select AI Demo / ASTA canonical service]
  /api/asta/analyze/stream
  /api/profiles
  │
  ▼
[ADB ASTA repository/control plane]
  Vector KB / SQLTUNE summary / report repository
  │
  ▼
[BaseDB source direct runtime]
  DEVDO schema evidence, DBMS_XPLAN.DISPLAY_CURSOR, before/after metrics
```

## 3. Non-negotiable current rules

1. **OADT2 browser must not expose endpoint/source selectors.**
   - endpoint: fixed `/api/asta/analyze`
   - source: internally fixed `DEVDO` + `DB0903_LINK`
2. **OADT2 now owns the ASTA workflow locally.**
   - It must not call the retired external ASTA service.
3. **Profile dropdown must use local DB ASTA profiles.**
   - `GET /api/asta/profiles` filters selectable names starting with `ASTA` from the selected DB.
4. **Before and after SQL execution must both be source-side.**
   - Reports should not rely on ADB `REMOTE` one-line DB Link plans.
5. **READY/IDLE progress state must show no spinner.**
   - First spinner starts only after user clicks `튜닝보고서 작성`.
6. **Mobile SQL editor must not clip lower lines.**
   - Mobile hides line-number column and uses full-width textarea.
7. **No secrets in docs or UI.**

## 4. API contract

### 4.1 `POST /api/asta/analyze`

OADT2 request body may contain:

```json
{
  "sql": "select ...",
  "llm_profile": "ASTA_GPT55_PROFILE",
  "use_llm": true,
  "options": {
    "fetch_rows": 100,
    "benchmark_repeat": 1,
    "sqltune_timeout_seconds": 1800
  }
}
```

Local ASTA normalizes the UI payload with defaults:

```json
{
  "source_schema": "DEVDO",
  "source_db_link": "DB0903_LINK",
  "source_db_id": "DB0903_TESTDB"
}
```

The proxy calls the canonical SSE endpoint and returns the last `event: result` JSON.

### 4.2 `GET /api/asta/profiles`

Returns:

```json
{
  "source": "local_oadt2",
  "asta_default": "ASTA_GROK_GENAI_PROFILE",
  "profiles": [
    {
      "name": "ASTA_GPT55_PROFILE",
      "profile_name": "ASTA_GPT55_PROFILE",
      "display_name": "★ ASTA_GPT55_PROFILE",
      "provider": "OpenAI",
      "model": "gpt-5.5",
      "status": "ENABLED",
      "selectable": true,
      "default": false
    }
  ]
}
```

Only `ASTA*` names are returned to the assistant profile dropdown.

## 5. Environment variables

| 변수 | 기본값 | 설명 |
|---|---|---|
| ASTA 실행 | 앱 내부 `/api/asta/*` | 외부 ASTA 서버 호출 없음 |

## 6. UI requirements

### Desktop

- AI Profile selector
- sample SQL selector
- SQL textarea with line numbers
- run/download buttons
- 수행 이력 card next to editor
- Markdown result section below

### Mobile portrait/landscape

- side nav can collapse with `☰`
- no endpoint/source controls
- line numbers hidden
- SQL textarea full width
- 수행 이력 below editor/actions
- result Markdown wraps long lines
- `100dvh` used where possible for iOS dynamic viewport

## 7. Result quality checklist

A valid local ASTA result should include:

- `architecture = PYTHON_ASTA_STREAM`
- detailed Markdown report
- before SQL and XPLAN
- after SQL and XPLAN when candidate exists
- before/after metrics in seconds or clear unit labels
- Vector KB summary
- SQL Tuning Advisor summary
- DBA review notes
- execution history
- `BASEDB_SOURCE_DIRECT` evidence for source-side plan collection

## 8. Test plan

```bash
node --check static/js/app.js
node --check static/js/extensions/tuning_assistant.js
uv run pytest tests/test_tuning_assistant_static.py tests/test_asta_proxy.py -q
```

Profile proxy smoke:

```bash
curl -sS http://127.0.0.1:8000/api/asta/profiles | python3 -m json.tool
```

Analyze smoke:

```bash
curl -sS http://127.0.0.1:8000/api/asta/analyze \
  -H 'Content-Type: application/json' \
  -d '{"sql":"select /* smoke */ 1 from dual","use_llm":false}'
```

## 9. Historical note

The original plan in this file targeted browser/ORDS direct execution and later a remote ASTA service. That is no longer the active OADT2 integration model. OADT2 should call only its same-origin `/api/asta/*` routes and run the ASTA workflow locally in this repository.


## 10. 테스트 완료 후 아래 작업 진행해줘.

https://github.com/primelyson2/ai-poc-descente/tree/ASTA
이 브런치 내가 만들었는 이거 설치 한 다음,
내가 zip 파일로 작업한 내역 /home/ubuntu/descente_poc_ui/ai-poc-descente-main 을 해당 브런치에 올려줘.