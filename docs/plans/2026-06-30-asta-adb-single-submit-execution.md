# ASTA ADB 단일 제출 실행 전환 계획

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** MCP·ORDS·Web UI가 동일한 ADB 공개 패키지에 작업을 한 번 제출하면 ADB 내부 Job이 전체 ASTA 파이프라인을 수행하고 영속화된 최종 결과서를 제공하도록 전환한다.

**Architecture:** `ASTA_PKG.SUBMIT_RUN`은 입력과 `run_id`를 `ASTA_RUNS`에 `QUEUED`로 저장하고 `DBMS_SCHEDULER` Job을 등록한 뒤 즉시 접수 JSON을 반환한다. Scheduler는 공개 진입점 `ASTA_PKG.EXECUTE_RUN(run_id)`을 호출하고, 기존 전체 오케스트레이션은 저장된 요청을 읽어 ADB → allowlisted DB Link → Source 패키지 경계 안에서 수행한다. `ANALYZE_SQL`은 기존 호출자 호환을 위해 submit 계약으로 전환하고, 상태·진행·결과서 조회 API는 유지한다.

**Tech Stack:** Oracle PL/SQL, DBMS_SCHEDULER, ORDS, FastAPI thin proxy, pytest 정적/계약 테스트, python-oracledb 실환경 smoke test.

---

### Task 1: 비동기 공개 계약 테스트

**Objective:** 구현 전에 원하는 공개 API와 비동기 상태 계약을 고정한다.

**Files:**
- Create: `tests/test_asta_adb_async_submit_contract.py`
- Test: `db/adb/asta_pkg.sql`
- Test: `db/ords/asta_ords_module.sql`

**Steps:**
1. `SUBMIT_RUN`, `EXECUTE_RUN`, `QUEUED`, Scheduler 등록, 저장 요청 조회를 요구하는 테스트를 작성한다.
2. 대상 테스트를 실행해 현재 동기 구현에서 예상대로 실패하는지 확인한다.
3. 테스트 오류가 아닌 누락 기능 때문에 실패하는지 확인한다.

### Task 2: 저장소 요청·멱등성 필드

**Objective:** MCP 재시도와 Scheduler 실행에 필요한 원본 요청을 ADB에 영속화한다.

**Files:**
- Modify: `db/asta/001_asta_repository.sql`
- Create: `db/asta/005_asta_async_run_columns.sql`
- Modify: `tools/asta_deploy_adb.py`
- Test: `tests/test_asta_adb_async_submit_contract.py`

**Steps:**
1. 신규 설치 DDL과 기존 설치용 additive migration에 `request_json`, `idempotency_key`, `job_name`, `submitted_at`을 추가한다.
2. 배포 도구가 컬럼 존재 여부를 확인해 migration을 안전하게 적용하도록 한다.
3. 대상 테스트를 통과시킨다.

### Task 3: SUBMIT_RUN tracer bullet

**Objective:** 요청을 QUEUED 상태로 저장하고 즉시 run_id를 반환한다.

**Files:**
- Modify: `db/adb/asta_pkg.sql`
- Test: `tests/test_asta_adb_async_submit_contract.py`

**Steps:**
1. 실패 테스트에 접수 응답 필드(`run_id`, `status=QUEUED`, `execution_mode=ADB_SCHEDULER`)를 추가한다.
2. `SUBMIT_RUN`이 run_id·SQL·source/profile·request JSON을 검증·저장하도록 최소 구현한다.
3. 같은 idempotency key 요청은 기존 run을 반환하고 다른 payload 충돌은 실패시키도록 한다.
4. 대상 테스트를 통과시킨다.

### Task 4: EXECUTE_RUN과 Scheduler

**Objective:** ADB가 저장된 요청만으로 전체 파이프라인을 수행한다.

**Files:**
- Modify: `db/adb/asta_pkg.sql`
- Test: `tests/test_asta_adb_async_submit_contract.py`
- Test: `tests/test_asta_adb_ords_static_contracts.py`

**Steps:**
1. `EXECUTE_RUN(run_id)` 공개 프로시저와 안전한 Scheduler job name 계약 테스트를 작성하고 실패를 확인한다.
2. `SUBMIT_RUN`이 commit된 run에 대해 `DBMS_SCHEDULER.CREATE_JOB`을 등록하도록 한다.
3. `EXECUTE_RUN`이 `request_json`을 읽고 기존 오케스트레이션을 실행하도록 분리한다.
4. 기존 `INSERT ASTA_RUNS`를 queued row의 `RUNNING` 전환으로 바꾸고 동시·중복 실행을 차단한다.
5. 예외 시 `FAILED`, error, report가 항상 영속화되도록 검증한다.

### Task 5: ORDS·FastAPI·UI 호환

**Objective:** 기존 `/analyze` 호출자는 즉시 run_id를 받고 기존 polling 흐름을 그대로 사용한다.

**Files:**
- Modify: `db/ords/asta_ords_module.sql`
- Modify: ASTA FastAPI router의 실제 경로
- Modify: 필요 시 `static/js/extensions/tuning_assistant.js`
- Test: `tests/test_asta_ords_proxy.py`
- Test: `tests/test_asta_proxy.py`
- Test: `tests/test_tuning_assistant_static.py`

**Steps:**
1. ORDS `POST analyze`가 `ASTA_PKG.SUBMIT_RUN`을 호출하도록 테스트를 먼저 변경한다.
2. FastAPI가 자체 background worker를 만들지 않고 ORDS 접수 응답만 전달하는지 고정한다.
3. UI가 `QUEUED/RUNNING` 모두 polling하고 terminal 상태에서만 보고서를 조회하는지 검증한다.
4. MCP용 명칭과 동일한 `POST runs` alias가 필요하면 얇은 ORDS handler로 추가하되 기존 endpoint를 유지한다.

### Task 6: 자동·정적·실환경 검증

**Objective:** 컴파일 전 계약 회귀와 실제 ADB 실행을 모두 검증한다.

**Files:**
- Modify: `tools/asta_smoke_adb.py`
- Modify: `docs/OADT2_ASTA_ARCHITECTURE.md`

**Steps:**
1. 전체 pytest를 실행한다.
2. SQL/PLSQL 정적 계약과 배포 순서 테스트를 실행한다.
3. 독립 리뷰로 중복 실행, transaction 경계, Scheduler 권한, stale RUNNING, idempotency 충돌을 점검한다.
4. 외부 DB 변경 전 사용자 승인을 받은 뒤 패키지·migration·ORDS만 targeted deploy한다.
5. `USER_OBJECTS`가 모두 `VALID`, `USER_ERRORS`가 0건인지 확인한다.
6. 짧고 bounded한 SQL을 submit해 최초 응답이 즉시 `QUEUED/RUNNING`인지 확인한다.
7. polling으로 `COMPLETED`까지 확인하고 결과서·Before/After·판정·진행 11단계를 검증한다.
8. 동일 idempotency key 재제출이 같은 run을 반환하고 중복 Job을 만들지 않는지 확인한다.
