# OADT2 문서 안내

최종 업데이트: 2026-06-26

이 폴더는 Oracle AI DB Test Tool 2(OADT2)의 운영/개발 문서를 모아둔 곳입니다. 현재 OADT2에서 가장 많이 변경된 영역은 **AI SQL Tuning Assistant(ASTA)** 이며, ASTA는 Python-local 실행 구조가 아니라 **ADB ORDS + PL/SQL 중심 구조**를 기준으로 설명합니다.

## 먼저 볼 문서

| 문서 | 용도 |
|---|---|
| `OADT2_ASTA_ARCHITECTURE.md` | ASTA 내부 API, ORDS endpoint, ADB/Source PL/SQL package, 전체 수행 순서도 |
| `AI_SQL_TUNING_ASSISTANT_MANUAL.md` | 사용자/운영자용 ASTA 화면 사용법, endpoint, 장애 대응 |
| `plans/2026-06-26-oadt2-asta-adb-ords-migration-workplan.md` | Python-local → ADB/ORDS 전환 작업서와 완료 기준 |
| `plans/2026-06-25-ai-sql-tuning-assistant-ords-adb-plan.md` | 과거/중간 설계 기록. 현재 구조와 다를 수 있으므로 참조용 |

## ASTA 현재 기준 요약

```text
Browser / OADT2 UI
  → FastAPI /api/asta/*
  → ADB ORDS /ords/asta/*
  → ADB ASTA_PKG + 보조 package
  → Source BaseDB ASTA_SOURCE_PKG via allowlisted DB Link
```

중요 원칙:

```text
- FastAPI는 ORDS_PROXY_ONLY 역할이다.
- Python에서 SQL/XPLAN/SQLTUNE/Vector/LLM/report를 직접 수행하지 않는다.
- Source DB 직접 접속, SSH tunnel, thick-mode subprocess는 ASTA production path에서 금지한다.
- Source 실제 evidence는 ADB PL/SQL → DB Link → Source helper package 경로로 수집한다.
- DB Link 경로에서 불가능한 단계는 직접 우회하지 않고 FAILED/SKIPPED로 표시한다.
```

## 관련 코드 위치

| 영역 | 경로 |
|---|---|
| OADT2 FastAPI thin proxy | `app/routers/asta_proxy.py` |
| ASTA UI extension | `static/js/extensions/tuning_assistant.js` |
| ADB repository DDL | `db/asta/` |
| ADB PL/SQL packages | `db/adb/` |
| Source BaseDB helper package | `db/source/asta_source_pkg.sql` |
| ORDS module | `db/ords/asta_ords_module.sql` |
| 배포/검증 SQL | `db/deploy/` |
| ADB 배포 도구 | `tools/asta_deploy_adb.py` |
| Source 배포 도구 | `tools/asta_deploy_source.py` |
| ADB smoke 도구 | `tools/asta_smoke_adb.py` |

## 검증 명령

```bash
cd /home/ubuntu/descente_poc_ui/ai-poc-descente-main
node --check static/js/extensions/tuning_assistant.js
uv run python -m py_compile app/routers/asta_proxy.py
uv run --with pytest pytest tests/test_asta_proxy.py tests/test_asta_adb_ords_static_contracts.py tests/test_asta_ords_migration_contract.py tests/test_tuning_assistant_static.py -q
```

## 문서 관리 규칙

- 현재 실행 구조는 `OADT2_ASTA_ARCHITECTURE.md`를 기준으로 갱신합니다.
- 오래된 Python-local 또는 source-direct fallback 설명은 현재 구조로 오해되지 않게 `과거 기록`으로 표시하거나 제거합니다.
- Credential, password, wallet, private key, raw secret 값은 문서에 쓰지 않습니다.
- 고객/사용자에게 보여줄 문서는 raw 내부 오류/secret이 아니라 요약과 DBA action 중심으로 작성합니다.
