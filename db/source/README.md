# ASTA Source Helper

Source BaseDB에서 ASTA의 제한된 SELECT 실행 근거를 수집하도록 허용된 스키마에만 `asta_source_pkg.sql`을 설치한다.

OADT2 FastAPI 애플리케이션은 이 데이터베이스에 직접 연결하면 안 된다. ADB는 허용 목록에 등록된 DB Link를 통해 helper를 호출하고, ORDS는 ADB 패키지만 외부에 노출한다.

## 설치 개요

Source helper 소유자 계정으로 다음 스크립트를 실행한다.

```sql
@db/deploy/01_source_compile.sql
@db/deploy/04_source_smoke.sql
```

`01_source_compile.sql`은 SQL만 사용하는 표준 설치 경로이다. 이 스크립트는 DB Link에서 안전하게 사용할 수 있는 chunk 계약에 필요한 Source 저장소 테이블을 생성하거나 확인한 후 `ASTA_SOURCE_PKG`를 컴파일한다.

- `ASTA_SOURCE_RESULTS(run_id, response_json, created_at)`는 `run_evidence_store_proc`가 반환하는 전체 `asta.v1` 실행 근거 JSON CLOB을 저장한다.
- `ASTA_SOURCE_ADVISOR_RESULTS(run_id, status, report, created_at)`는 Source Scheduler 경로에서 생성된 선택적 SQL Tuning Advisor 결과를 저장한다.
- `created_at` 인덱스는 기간 기준 데이터 정리를 지원한다. ADB가 chunk를 모두 가져와 결과서를 저장할 때까지 행을 유지하고, 이후 배포 환경의 보존 기간 정책에 따라 `created_at` 기준으로 오래된 행을 삭제한다.

Source BaseDB에서 DBA가 다음 권한을 부여해야 한다.

```sql
GRANT SELECT  ON v_$sql                     TO <helper_owner>;
GRANT SELECT  ON v_$sql_plan_statistics_all TO <helper_owner>;
GRANT EXECUTE ON dbms_xplan                 TO <helper_owner>;
GRANT EXECUTE ON dbms_sqltune               TO <helper_owner>;
```

`DBMS_SQLTUNE`은 ADB가 `p_run_advisor => 'Y'`를 전달한 경우에만 사용한다.
ADB가 `DEVDO.asta_source_pkg@DB0903_LINK`와 같이 스키마를 명시한 DB Link 호출을 사용하는 경우, DB Link 사용자에게 `ASTA_SOURCE_PKG`의 `EXECUTE` 권한을 부여하거나 해당 스키마 자체를 Source helper 소유자로 사용한다.

## 런타임 계약

`ASTA_SOURCE_PKG.RUN_EVIDENCE`는 SELECT 또는 WITH SQL을 입력받아 `ASTA_RUN_ID` 표식을 삽입하고, 제한된 `COUNT(*)` 래퍼를 실행한 뒤 다음 정보를 JSON으로 반환한다.

- 명시적인 `status`
- 커서 실행 통계
- `DBMS_XPLAN.DISPLAY_CURSOR` 출력
- 선택적인 SQL Tuning Advisor 결과

안전성 검사나 실행에 실패하면 ADB Bridge가 이후 ASTA 단계를 결정론적으로 중단할 수 있도록 `status:"FAILED"`와 `error` 객체를 반환한다.

helper는 실행 SQL의 주석 표식에 `p_run_id`를 삽입하기 전에 값을 검증한다. 짧은 영문·숫자 ID와 `_`, `.`, `:`, `-` 문자만 표식으로 허용한다.

`p_repeat_policy`는 실행 전에 정규화하며 다음 값만 허용한다.

- `AUTO`
- `ONCE`
- `REPEAT:<n>`

반복 횟수는 패키지의 최대 허용값을 넘지 않도록 제한한다.

`p_run_advisor`와 `p_sqltune_time_sec`는 ADB Bridge뿐 아니라 Source helper 내부에서도 다시 정규화한다. 응답에 `advisor_requested`와 `sqltune_time_limit_sec`를 포함하므로 ADB의 진행 상태 및 결과서 처리 로직이 SQL Tuning Advisor가 요청에 의해 생략되었는지, 실행 중 실패했는지 구분할 수 있다.

성공 및 실패 JSON 응답에는 다음 계약 정보가 포함된다.

```text
contract_version: "asta.v1"
execution_boundary: "SOURCE_BASEDB_DBLINK_ONLY"
guard_policy: "SELECT_WITH_SINGLE_STATEMENT"
```

이 값을 통해 ADB와 ORDS 소비자는 Source 실행이 단일 SELECT 또는 WITH 문만 허용하는 안전성 검사 범위 안에서 수행되었는지 확인할 수 있다.

성공 응답에는 다음 실행 근거 정보도 포함된다.

```text
evidence_method: "BOUNDED_COUNT_GATHER_PLAN_STATS"
metrics_source: "V$SQL_PLAN_STATISTICS_ALL_LAST"
timing_scope: "repeat_loop_total"
elapsed_wall_ms_per_exec
```

ADB의 비교 로직은 이 값을 이용해 Source 커서의 `LAST_*` 통계와 helper의 제한 실행 래퍼 및 반복 루프의 실제 경과 시간을 구분한다.

## DB Link chunk JSON 계약

Oracle DB Link를 통한 원격 PL/SQL 호출에서는 CLOB을 안전하게 전달하거나 반환하기 어렵다. 따라서 ADB는 DB Link를 통해 `RUN_EVIDENCE`를 직접 호출하지 않고 Source 저장 및 chunk 조회 API를 사용해야 한다.

1. ADB는 허용 목록 테이블 `ASTA_SOURCE_CONNECTIONS`에서 `source_db_id`를 조회한다. 브라우저와 FastAPI의 요청 payload는 `source_schema` 또는 DB Link 이름을 지정할 수 없다.
2. ADB는 DB Link를 통해 `ASTA_SOURCE_PKG.RUN_EVIDENCE_STORE_PROC@<DB_LINK>(..., p_status_json OUT)`를 호출하고 SQL은 `VARCHAR2`로 전달한다. 호출이 성공하면 `{"status":"STORED","contract_version":"asta.v1",...}`를 반환하고 전체 JSON CLOB을 Source의 `ASTA_SOURCE_RESULTS`에 저장한다.
3. ADB는 `ASTA_SOURCE_PKG.GET_RESULT_CHUNK@<DB_LINK>(run_id, offset, 8000)`를 반복 호출한다. 각 chunk를 이어 붙이고 `NULL` 또는 요청 크기보다 짧은 chunk가 반환되면 조회를 종료한다.
4. 재조립한 JSON은 `contract_version:"asta.v1"` 형식이어야 하며, 일반적인 `status` 값은 `COMPLETED` 또는 구조화된 `FAILED`이다.

`db/deploy/04_source_smoke.sql`은 로컬 직접 CLOB 경로와 저장·chunk 조회 경로를 모두 검증한다. `get_result_chunk` 결과를 다시 조립해 JSON 계약이 올바른지 확인한다.

SQL 안전성 검사는 금지 키워드를 검사하기 전에 주석과 문자열 리터럴을 제거한다. 따라서 SELECT 문자열 안의 `'drop'`과 같은 무해한 값은 잘못 차단하지 않으면서 실제 실행 SQL의 위험한 키워드는 계속 검사한다.

helper는 정확히 하나의 제한된 SELECT 또는 WITH 문만 실행하므로 세미콜론 문장 종료자를 허용하지 않는다. 독립된 SQL*Plus `/` 종료 행도 같은 이유로 거부한다.

허용하는 SQL 길이는 32KB로 제한한다. 이를 통해 `VARCHAR2` 기반 안전성 검사가 이후 실제로 실행할 SQL과 동일한 내용을 검사하도록 보장한다.

비밀번호, Wallet 경로 또는 애플리케이션 비밀정보를 이 SQL 파일이나 문서에 기록하면 안 된다.
