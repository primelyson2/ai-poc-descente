# ASTA ADB Repository

ADB `ASTA_PKG` 실행 이력, 진행상태, 보고서 JSON/Markdown 저장용 DDL입니다.

`003_asta_runs_source_db_id.sql` is an idempotent additive migration for
environments where `ASTA_RUNS` was created before `SOURCE_DB_ID` was added.
