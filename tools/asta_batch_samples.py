"""약 1분 실행을 목표로 한 Real ASTA BATCH 샘플과 결정론적 개선 후보."""

from __future__ import annotations


DAILY_FILTER = "COMP_CD='01' AND SALE_DE BETWEEN '20250101' AND '20251231'"
MONTHLY_FILTER = "COMP_CD='01' AND SALE_YM BETWEEN '202501' AND '202512'"
BASE_METRICS = (
    ("TOTAL_QTY", "SUM(SALE_QTY)"),
    ("TOTAL_AMT", "SUM(SALE_AMT)"),
    ("REAL_AMT", "SUM(REAL_SALE_AMT)"),
    ("COST_AMT", "SUM(SALE_COST_AMT)"),
    ("STD3_QTY", "SUM(CASE WHEN SALE_STD_CD='3' THEN SALE_QTY ELSE 0 END)"),
    ("KIND1_QTY", "SUM(CASE WHEN SALE_KIND_CD='1' THEN SALE_QTY ELSE 0 END)"),
    ("BSAL23_AMT", "SUM(CASE WHEN BSAL_CLS_CD IN ('2','3') THEN SALE_AMT ELSE 0 END)"),
    ("NORMAL_QTY", "SUM(CASE WHEN NOR_CLS_CD='1' THEN SALE_QTY ELSE 0 END)"),
)
METRICS = tuple(
    (f"S{section}_{alias}", expression)
    for section in range(1, 6)
    for alias, expression in BASE_METRICS
)


def _original_sql(dimension: str) -> str:
    branches = [
        (
            f"SELECT {dimension}, '{alias}' METRIC, {expression} METRIC_VALUE\n"
            f"FROM DSNT.TSE_SALE_DAY_S WHERE {DAILY_FILTER} GROUP BY {dimension}"
        )
        for alias, expression in METRICS
    ]
    return "\nUNION ALL\n".join(branches)


def _candidate_sql(dimension: str) -> str:
    expressions = ",\n       ".join(f"{expression} {alias}" for alias, expression in METRICS)
    unpivot_items = ", ".join(f"{alias} AS '{alias}'" for alias, _ in METRICS)
    return f"""WITH A AS (
  SELECT {dimension}, {expressions}
  FROM DSNT.TSE_SALE_MON_S WHERE {MONTHLY_FILTER} GROUP BY {dimension}
)
SELECT {dimension}, METRIC, METRIC_VALUE
FROM A UNPIVOT INCLUDE NULLS (
  METRIC_VALUE FOR METRIC IN ({unpivot_items})
)"""


def _sample(number: int, label: str, pattern: str, dimension: str) -> dict:
    return {
        "id": f"asta-batch-{number:02d}",
        "label": f"B{number:02d} · {label}",
        "pattern": pattern,
        "workload": "BATCH",
        "sql": _original_sql(dimension),
        "candidate_sql": _candidate_sql(dimension),
        "change_summary": (
            "5개 보고서 섹션의 2025년 일판매 KPI 40개를 각각 재집계하던 UNION ALL을 "
            "월판매 요약 1회 집계와 UNPIVOT으로 전환"
        ),
    }


BATCH_SAMPLES = [
    _sample(1, "브랜드 KPI 반복 집계", "BATCH_BRAND_KPI_RESCAN", "BRAND_CD"),
    _sample(2, "상품분류 KPI 반복 집계", "BATCH_CLASS_KPI_RESCAN", "CLASS_CD"),
    _sample(3, "성별 KPI 반복 집계", "BATCH_GENDER_KPI_RESCAN", "GENDER_CD"),
    _sample(4, "라인 KPI 반복 집계", "BATCH_LINE_KPI_RESCAN", "LINE_CD"),
    _sample(5, "판매기준 KPI 반복 집계", "BATCH_SALE_STANDARD_KPI_RESCAN", "SALE_STD_CD"),
]


SAMPLE_BY_ID = {sample["id"]: sample for sample in BATCH_SAMPLES}
