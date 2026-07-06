"""ASTA 최종 결과서의 persisted 11-stage timing 계약."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_report_build_accepts_persisted_progress_and_pipeline_elapsed_snapshot():
    report = read("db/adb/asta_report_pkg.sql")
    main = read("db/adb/asta_pkg.sql")

    assert report.count("p_progress_json        IN CLOB DEFAULT NULL") >= 2
    assert report.count("p_pipeline_elapsed_ms  IN NUMBER DEFAULT NULL") >= 2
    assert main.count("p_progress_json        => l_progress_json") >= 4
    assert main.count("p_pipeline_elapsed_ms  => l_pipeline_elapsed_ms") == 2


def test_report_renders_all_eleven_stages_from_progress_without_inventing_zero():
    report = read("db/adb/asta_report_pkg.sql")

    assert "PROCEDURE append_stage_timing" in report
    assert "## 단계별 소요시간" in report
    assert "FOR l_seq IN 1..11 LOOP" in report
    assert "ASTA_RUN_PROGRESS" in report
    assert "WHEN 'DONE' THEN 'COMPLETED'" in report
    for status in ("QUEUED", "RUNNING", "SKIPPED", "FAILED", "COMPLETED"):
        assert status in report
    assert "측정 불가/미기록" in report
    assert "NVL(l_elapsed_ms, 0)" not in report
    assert "COALESCE(l_elapsed_ms, 0)" not in report


def test_all_durations_are_rendered_as_decimal_seconds_and_totals_are_distinguished():
    report = read("db/adb/asta_report_pkg.sql")

    assert "FUNCTION elapsed_seconds_text" in report
    assert "p_elapsed_ms / 1000" in report
    assert "' s'" in report
    assert "단계 소요시간 합계" in report
    assert "파이프라인 E2E" in report
    assert "단계가 겹칠 수 있어 E2E와 동일하지 않을 수 있습니다" in report
    assert "Elapsed (ms)" not in report


def test_report_does_not_render_legacy_millisecond_or_microsecond_units():
    report = read("db/adb/asta_report_pkg.sql")

    for legacy_label in (
        "Wall Time 합계(ms)",
        "Wall Time/Exec(ms)",
        "LAST Elapsed(us)",
        "Elapsed (μs)",
        "elapsed_time_us `",
        "after elapsed_time_us",
    ):
        assert legacy_label not in report


def test_main_captures_terminal_progress_before_final_timed_report_build():
    main = read("db/adb/asta_pkg.sql")

    done = main.index("record_progress(l_run_id, 10, 'FINAL_REPORT', 'Final report synthesis', 'DONE')")
    progress = main.index("l_progress_json := build_progress_array_json(l_run_id)", done)
    elapsed = main.index("l_pipeline_elapsed_ms :=", progress)
    timed_report = main.index("p_progress_json        => l_progress_json", elapsed)
    assert done < progress < elapsed < timed_report
