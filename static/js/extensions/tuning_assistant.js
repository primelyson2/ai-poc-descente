/**
 * tuning_assistant.js — ASTA 연동용 독립 view.
 * 작성자: 도상훈
 * 파일 용도: OADT2 화면에서 ASTA SQL 튜닝 요청, 진행률 폴링, 결과/리포트 렌더링을 담당한다.
 *
 * 기존 화면 소스와 분리하기 위해 window.Views.tuningAssistant 만 추가한다.
 * 실제 ASTA API 연결은 OADT2 same-origin /api/asta/analyze proxy를 사용한다.
 * 엔드포인트를 호출하도록 구성했다.
 */
(function () {
  window.Views = window.Views || {};

  const DEFAULT_ORDS_BASE_URL = "/api/asta";
  const DEFAULT_ENDPOINT = `${DEFAULT_ORDS_BASE_URL}/analyze`;
  const DEFAULT_SOURCE_ID = "DB0903_TESTDB";
  const DEFAULT_AI_PROFILE = "ASTA_GPT5_PROFILE";
  const ASTA_SAMPLE_SQLS = [
    {
      id: "asta-ui-01",
      label: "01. 악성: SALES 8회 반복 스캔 UNION ALL",
      sql: `select /* ASTA_UI_MALICIOUS_01_repeat_sales_8_scans */ bucket, cnt, amt
from (
  select 'year_1998' bucket, count(*) cnt, sum(s.amount_sold) amt from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=1998
  union all
  select 'year_1999' bucket, count(*) cnt, sum(s.amount_sold) amt from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=1999
  union all
  select 'year_2000' bucket, count(*) cnt, sum(s.amount_sold) amt from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=2000
  union all
  select 'year_2001' bucket, count(*) cnt, sum(s.amount_sold) amt from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=2001
  union all
  select 'channel_2' bucket, count(*) cnt, sum(s.amount_sold) amt from DEVDO.SALES s where s.channel_id=2
  union all
  select 'channel_3' bucket, count(*) cnt, sum(s.amount_sold) amt from DEVDO.SALES s where s.channel_id=3
  union all
  select 'promo_exists' bucket, count(*) cnt, sum(s.amount_sold) amt from DEVDO.SALES s where exists (select 1 from DEVDO.PROMOTIONS p where p.promo_id=s.promo_id)
  union all
  select 'cost_exists' bucket, count(*) cnt, sum(s.amount_sold) amt from DEVDO.SALES s where exists (select 1 from DEVDO.COSTS k where k.prod_id=s.prod_id and k.time_id=s.time_id and k.channel_id=s.channel_id)
)
order by bucket`,
    },
    {
      id: "asta-ui-02",
      label: "02. 악성: PRODUCTS별 SALES 상관 서브쿼리 7개",
      sql: `select /* ASTA_UI_MALICIOUS_02_many_product_scalar_subqueries */
       p.prod_id,
       p.prod_name,
       p.prod_category,
       (select count(*) from DEVDO.SALES s where s.prod_id=p.prod_id) sales_cnt,
       (select sum(s.amount_sold) from DEVDO.SALES s where s.prod_id=p.prod_id) amount_sum,
       (select sum(s.quantity_sold) from DEVDO.SALES s where s.prod_id=p.prod_id) qty_sum,
       (select count(distinct s.cust_id) from DEVDO.SALES s where s.prod_id=p.prod_id) buyer_cnt,
       (select count(*) from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where s.prod_id=p.prod_id and t.calendar_year=1998) y1998_cnt,
       (select count(*) from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where s.prod_id=p.prod_id and t.calendar_year=1999) y1999_cnt,
       (select avg(k.unit_cost) from DEVDO.COSTS k where k.prod_id=p.prod_id) avg_cost
from DEVDO.PRODUCTS p
where p.prod_category is not null
order by amount_sum desc nulls last`,
    },
    {
      id: "asta-ui-03",
      label: "03. 악성: 잘못된 INDEX 힌트 + 함수 predicate",
      sql: `select /*+ index(s SALES_PROMO_BIX) index(t TIMES_PK) leading(t s p) use_nl(s p) */ /* ASTA_UI_MALICIOUS_03_bad_index_hint_function_predicate */
       to_char(t.calendar_year) yy,
       substr(upper(p.prod_category),1,20) category,
       count(*) cnt,
       sum(s.amount_sold) amt
from DEVDO.TIMES t
join DEVDO.SALES s on s.time_id=t.time_id
join DEVDO.PRODUCTS p on p.prod_id=s.prod_id
where to_char(t.calendar_year) in ('1998','1999','2000','2001')
  and substr(upper(nvl(p.prod_category,'UNKNOWN')),1,1) between 'A' and 'Z'
  and nvl(s.amount_sold,0) + nvl(s.quantity_sold,0) > 0
group by to_char(t.calendar_year), substr(upper(p.prod_category),1,20)
order by amt desc`,
    },
    {
      id: "asta-ui-04",
      label: "04. 악성: SALES self join 4회로 row 폭증",
      sql: `select /*+ leading(s1 s2 s3 s4) use_hash(s2) use_hash(s3) use_hash(s4) */ /* ASTA_UI_MALICIOUS_04_sales_self_join_explosion */
       s1.prod_id,
       s1.channel_id,
       count(*) join_rows,
       sum(s1.amount_sold) amt1,
       sum(s2.amount_sold) amt2,
       sum(s3.amount_sold) amt3,
       sum(s4.amount_sold) amt4
from DEVDO.SALES s1
join DEVDO.SALES s2 on s2.prod_id=s1.prod_id and s2.channel_id=s1.channel_id
join DEVDO.SALES s3 on s3.cust_id=s1.cust_id and s3.time_id=s1.time_id
join DEVDO.SALES s4 on s4.prod_id=s1.prod_id and s4.time_id=s1.time_id
join DEVDO.TIMES t on t.time_id=s1.time_id
where t.calendar_year=1999
  and s1.amount_sold > 0
  and s2.amount_sold > 0
  and s3.amount_sold > 0
  and s4.amount_sold > 0
group by s1.prod_id, s1.channel_id
having count(*) > 50
order by join_rows desc`,
    },
    {
      id: "asta-ui-05",
      label: "05. 악성: 같은 SALES/COSTS 집계를 CTE 5개로 중복 계산",
      sql: `with q1998 as (
  select /*+ materialize */ /* ASTA_UI_MALICIOUS_05_duplicate_cte_scans */ s.prod_id, s.channel_id, sum(s.amount_sold - s.quantity_sold*nvl(k.unit_cost,0)) margin
  from DEVDO.SALES s left join DEVDO.COSTS k on k.prod_id=s.prod_id and k.time_id=s.time_id and k.channel_id=s.channel_id
  join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=1998 group by s.prod_id, s.channel_id
), q1999 as (
  select /*+ materialize */ s.prod_id, s.channel_id, sum(s.amount_sold - s.quantity_sold*nvl(k.unit_cost,0)) margin
  from DEVDO.SALES s left join DEVDO.COSTS k on k.prod_id=s.prod_id and k.time_id=s.time_id and k.channel_id=s.channel_id
  join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=1999 group by s.prod_id, s.channel_id
), q2000 as (
  select /*+ materialize */ s.prod_id, s.channel_id, sum(s.amount_sold - s.quantity_sold*nvl(k.unit_cost,0)) margin
  from DEVDO.SALES s left join DEVDO.COSTS k on k.prod_id=s.prod_id and k.time_id=s.time_id and k.channel_id=s.channel_id
  join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=2000 group by s.prod_id, s.channel_id
), q2001 as (
  select /*+ materialize */ s.prod_id, s.channel_id, sum(s.amount_sold - s.quantity_sold*nvl(k.unit_cost,0)) margin
  from DEVDO.SALES s left join DEVDO.COSTS k on k.prod_id=s.prod_id and k.time_id=s.time_id and k.channel_id=s.channel_id
  join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=2001 group by s.prod_id, s.channel_id
), qall as (
  select /*+ materialize */ s.prod_id, s.channel_id, sum(s.amount_sold - s.quantity_sold*nvl(k.unit_cost,0)) margin
  from DEVDO.SALES s left join DEVDO.COSTS k on k.prod_id=s.prod_id and k.time_id=s.time_id and k.channel_id=s.channel_id group by s.prod_id, s.channel_id
)
select qall.prod_id, qall.channel_id,
       nvl(q1998.margin,0)+nvl(q1999.margin,0)+nvl(q2000.margin,0)+nvl(q2001.margin,0)+nvl(qall.margin,0) total_margin
from qall
left join q1998 on q1998.prod_id=qall.prod_id and q1998.channel_id=qall.channel_id
left join q1999 on q1999.prod_id=qall.prod_id and q1999.channel_id=qall.channel_id
left join q2000 on q2000.prod_id=qall.prod_id and q2000.channel_id=qall.channel_id
left join q2001 on q2001.prod_id=qall.prod_id and q2001.channel_id=qall.channel_id
order by total_margin desc`,
    },
    {
      id: "asta-ui-06",
      label: "06. 악성: OR 조건 남발 + NVL/TO_CHAR로 인덱스 방해",
      sql: `select /* ASTA_UI_MALICIOUS_06_or_nvl_to_char_predicates */
       p.prod_category,
       ch.channel_desc,
       count(*) cnt,
       sum(s.amount_sold) amt
from DEVDO.SALES s
join DEVDO.TIMES t on t.time_id=s.time_id
join DEVDO.PRODUCTS p on p.prod_id=s.prod_id
join DEVDO.CHANNELS ch on ch.channel_id=s.channel_id
where (to_char(t.calendar_year)='1998' or to_char(t.calendar_year)='1999' or to_char(t.calendar_year)='2000' or to_char(t.calendar_year)='2001')
  and (nvl(s.channel_id,-1)=2 or nvl(s.channel_id,-1)=3 or nvl(s.channel_id,-1)=4 or nvl(s.channel_id,-1)=9)
  and (upper(p.prod_category) like '%E%' or upper(p.prod_category) like '%A%' or upper(p.prod_category) like '%O%')
group by p.prod_category, ch.channel_desc
order by amt desc`,
    },
    {
      id: "asta-ui-07",
      label: "07. 악성: 고객별 EXISTS/NOT EXISTS로 SALES 재조회 반복",
      sql: `select /* ASTA_UI_MALICIOUS_07_nested_exists_rechecks */
       c.cust_id,
       c.cust_first_name,
       c.cust_last_name,
       co.country_region,
       count(s.prod_id) cnt,
       sum(s.amount_sold) amt
from DEVDO.CUSTOMERS c
join DEVDO.COUNTRIES co on co.country_id=c.country_id
join DEVDO.SALES s on s.cust_id=c.cust_id
join DEVDO.TIMES t on t.time_id=s.time_id
where t.calendar_year between 1998 and 2001
  and exists (select 1 from DEVDO.SALES sx where sx.cust_id=c.cust_id and sx.amount_sold > s.amount_sold/2)
  and exists (select 1 from DEVDO.SALES sp where sp.prod_id=s.prod_id and sp.channel_id=s.channel_id and sp.amount_sold > 0)
  and not exists (
    select 1 from DEVDO.SALES sy join DEVDO.TIMES ty on ty.time_id=sy.time_id
    where sy.cust_id=c.cust_id and sy.prod_id=s.prod_id and ty.calendar_year < t.calendar_year
  )
group by c.cust_id, c.cust_first_name, c.cust_last_name, co.country_region
having sum(s.amount_sold) > 100
order by amt desc`,
    },
    {
      id: "asta-ui-08",
      label: "08. 악성: 동일 fact 집계를 inline view 6개로 재계산",
      sql: `select /* ASTA_UI_MALICIOUS_08_six_duplicate_inline_views */
       a.prod_id,
       a.amt y1998_amt,
       b.amt y1999_amt,
       c.amt y2000_amt,
       d.amt y2001_amt,
       e.amt all_amt,
       f.buyers all_buyers
from (select s.prod_id, sum(s.amount_sold) amt from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=1998 group by s.prod_id) a
join (select s.prod_id, sum(s.amount_sold) amt from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=1999 group by s.prod_id) b on b.prod_id=a.prod_id
join (select s.prod_id, sum(s.amount_sold) amt from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=2000 group by s.prod_id) c on c.prod_id=a.prod_id
join (select s.prod_id, sum(s.amount_sold) amt from DEVDO.SALES s join DEVDO.TIMES t on t.time_id=s.time_id where t.calendar_year=2001 group by s.prod_id) d on d.prod_id=a.prod_id
join (select s.prod_id, sum(s.amount_sold) amt from DEVDO.SALES s group by s.prod_id) e on e.prod_id=a.prod_id
join (select s.prod_id, count(distinct s.cust_id) buyers from DEVDO.SALES s group by s.prod_id) f on f.prod_id=a.prod_id
where nvl(a.amt,0)+nvl(b.amt,0)+nvl(c.amt,0)+nvl(d.amt,0)+nvl(e.amt,0) > 1000
order by e.amt desc`,
    },
    {
      id: "asta-ui-09",
      label: "09. 악성: DISTINCT + analytic + 상관 재조회 혼합",
      sql: `with base as (
  select /* ASTA_UI_MALICIOUS_09_distinct_analytic_scalar_mix */
         s.prod_id, s.cust_id, s.channel_id, s.time_id, s.amount_sold, s.quantity_sold,
         t.calendar_year, p.prod_category, ch.channel_desc
  from DEVDO.SALES s
  join DEVDO.TIMES t on t.time_id=s.time_id
  join DEVDO.PRODUCTS p on p.prod_id=s.prod_id
  join DEVDO.CHANNELS ch on ch.channel_id=s.channel_id
  where t.calendar_year between 1998 and 2001
), ranked as (
  select distinct b.*,
         dense_rank() over(partition by b.cust_id order by b.amount_sold desc nulls last) cust_sale_rank,
         sum(b.amount_sold) over(partition by b.prod_id, b.calendar_year) prod_year_amt,
         (select count(*) from DEVDO.SALES sx where sx.cust_id=b.cust_id and sx.prod_id=b.prod_id) repeat_buy_cnt,
         (select max(sy.amount_sold) from DEVDO.SALES sy where sy.channel_id=b.channel_id and sy.time_id=b.time_id) channel_day_max
  from base b
)
select prod_category, channel_desc, calendar_year,
       count(distinct cust_id) buyers,
       sum(amount_sold) amt,
       avg(repeat_buy_cnt) avg_repeat_buy,
       max(channel_day_max) max_channel_day
from ranked
where cust_sale_rank <= 20
group by prod_category, channel_desc, calendar_year
order by amt desc`,
    },
    {
      id: "asta-ui-10",
      label: "10. 악성: ORDERED/USE_NL 힌트로 큰 테이블 반복 NL 유도",
      sql: `select /*+ ordered use_nl(s) use_nl(k) index(s SALES_PROMO_BIX) */ /* ASTA_UI_MALICIOUS_10_forced_nested_loops_bad_index */
       co.country_region,
       co.country_name,
       p.prod_category,
       p.prod_subcategory,
       ch.channel_desc,
       t.calendar_year,
       count(*) total_rows,
       sum(s.amount_sold) amount_sum,
       sum(s.quantity_sold) qty_sum,
       sum(s.quantity_sold * nvl(k.unit_cost,0)) cost_sum,
       (select count(*) from DEVDO.SALES sx where sx.prod_id=s.prod_id and sx.channel_id=s.channel_id) same_prod_channel_sales,
       (select avg(kx.unit_cost) from DEVDO.COSTS kx where kx.prod_id=s.prod_id and kx.channel_id=s.channel_id) avg_prod_channel_cost
from DEVDO.COUNTRIES co
join DEVDO.CUSTOMERS c on c.country_id=co.country_id
join DEVDO.SALES s on s.cust_id=c.cust_id
join DEVDO.TIMES t on t.time_id=s.time_id
join DEVDO.PRODUCTS p on p.prod_id=s.prod_id
join DEVDO.CHANNELS ch on ch.channel_id=s.channel_id
left join DEVDO.COSTS k on k.prod_id=s.prod_id and k.time_id=s.time_id and k.channel_id=s.channel_id
where t.calendar_year between 1998 and 2001
  and co.country_region is not null
  and p.prod_category is not null
group by co.country_region, co.country_name, p.prod_category, p.prod_subcategory, ch.channel_desc, t.calendar_year, s.prod_id, s.channel_id
having sum(s.amount_sold) > 100
order by amount_sum desc`,
    },
  ];
  const DEFAULT_STEPS = [
    { seq: 1, code: "REQUEST_RECEIVED", label: "요청 수신", status: "PENDING" },
    { seq: 2, code: "ORDS_DISPATCH", label: "ADB ORDS 분석 호출", status: "PENDING" },
    { seq: 3, code: "SQL_GUARD", label: "SQL 안전성 검사", status: "PENDING" },
    { seq: 4, code: "BEFORE_EVIDENCE", label: "원본 SQL Evidence 수집", status: "PENDING" },
    { seq: 5, code: "SQL_TUNING_ADVISOR", label: "Tuning Advisor 수행", status: "PENDING" },
    { seq: 6, code: "VECTOR_KB", label: "ADB Vector KB 유사 결과서 조회", status: "PENDING" },
    { seq: 7, code: "LLM_REWRITE", label: "AI 1차 튜닝: 분석결과 + Vector 사례 참조", status: "PENDING" },
    { seq: 8, code: "AFTER_EVIDENCE", label: "튜닝 SQL 분석: 튜닝 SQL 재수행/비교", status: "PENDING" },
    { seq: 9, code: "LLM_FINAL_REVIEW", label: "AI Before/After 정리", status: "PENDING" },
    { seq: 10, code: "FINAL_REPORT", label: "최종 보고서 생성", status: "PENDING" },
    { seq: 11, code: "VECTOR_SAVE", label: "ADB Vector KB 결과서 저장", status: "PENDING" },
  ];

  /**
   * 사용자/서버 문자열을 HTML로 렌더링하기 전에 이스케이프한다.
   */
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  /**
   * SQL 원문을 화면 표시용으로 줄바꿈/공백 정리한다.
   */
  function formatSql(sql) {
    const keywords = [
      "select", "from", "where", "group by", "order by", "having", "union all", "union",
      "inner join", "left join", "right join", "full join", "join", "on", "and", "or",
      "fetch first", "offset", "with"
    ];
    let formatted = String(sql || "").trim().replace(/\s+/g, " ");
    for (const keyword of keywords) {
      const pattern = new RegExp(`\\s+(${keyword.replace(/ /g, "\\\\s+")})\\s+`, "ig");
      formatted = formatted.replace(pattern, (_match, found) => `\n${found.toUpperCase()} `);
    }
    formatted = formatted
      .replace(/^\n+/, "")
      .replace(/,\s*/g, ",\n  ")
      .replace(/\n(AND|OR)\s+/g, "\n  $1 ")
      .replace(/\n(ON)\s+/g, "\n  $1 ")
      .replace(/\n+/g, "\n")
      .trim();
    return formatted;
  }

  /**
   * 밀리초 실행 시간을 사람이 읽기 쉬운 문자열로 변환한다.
   */
  function formatDuration(ms) {
    if (ms == null || Number.isNaN(Number(ms))) return "-";
    const total = Math.max(0, Math.round(Number(ms)));
    const sec = total / 1000;
    if (sec < 60) return `${sec.toFixed(1)}초`;
    const min = Math.floor(sec / 60);
    return `${min}분 ${(sec % 60).toFixed(1)}초`;
  }

  /**
   * ISO 시간 문자열을 밀리초 timestamp로 파싱한다.
   */
  function parseTimeMs(value) {
    if (!value) return null;
    const ms = new Date(value).getTime();
    return Number.isFinite(ms) ? ms : null;
  }

  /**
   * 진행 단계 목록에서 전체 경과 시간을 계산한다.
   */
  function totalElapsedMs(progress, steps, isComplete) {
    const explicit = progress?.totalDurationMs ?? progress?.total_duration_ms ?? progress?.elapsed_ms ?? progress?.elapsedMs;
    if (explicit != null && !Number.isNaN(Number(explicit))) return Number(explicit);
    const sec = progress?.elapsed_total_sec ?? progress?.elapsed_total_seconds ?? progress?.total_elapsed_sec ?? progress?.duration_sec;
    if (sec != null && !Number.isNaN(Number(sec))) return Number(sec) * 1000;
    const stepTimes = steps.map((item) => parseTimeMs(item.at)).filter((ms) => ms != null);
    const start = parseTimeMs(progress?.created_at || progress?.started_at || progress?.start_time)
      ?? Math.min(...stepTimes);
    if (!Number.isFinite(start)) return null;
    const end = parseTimeMs(progress?.completed_at || progress?.ended_at || progress?.end_time)
      ?? (isComplete ? Math.max(...stepTimes) : Date.now());
    if (!Number.isFinite(end)) return null;
    return Math.max(0, end - start);
  }

  /**
   * 리포트/원문 다운로드용 텍스트 파일을 브라우저에서 생성한다.
   */
  function downloadText(filename, text) {
    const blob = new Blob([text || ""], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  /**
   * UI 진행률에 표시할 한 단계의 상태와 시간 정보를 만든다.
   */
  function stepWithTiming(step, status, detail, at = new Date(), elapsedMs = null) {
    const iso = at ? (at instanceof Date ? at : new Date(at)).toISOString() : "";
    return { ...step, status, detail: detail || step.detail || status, at: iso, elapsed_ms: elapsedMs };
  }

  /**
   * ASTA analyze 결과와 다운로드 링크를 결과 영역에 렌더링한다.
   */
  function renderResult(target, data) {
    const report = data?.detailed_report_markdown || data?.report_markdown || data?.llm_final_report?.report_markdown || data?.report || data?.message || "";
    const runId = data?.run_id ? `<div class="muted">Run ID: ${escapeHtml(data.run_id)}</div>` : "";
    window.__astaLastReport = {
      runId: data?.run_id || "report",
      report: report || JSON.stringify(data, null, 2),
    };
    target.innerHTML = `
      <div class="card stack tuning-report-card" style="gap: var(--space-3);">
        <div class="tuning-report-head">
          <div>
            <div class="section-title">ASTA 분석 결과</div>
            ${runId}
          </div>
          <div class="tuning-report-actions" aria-label="결과서 스크롤 이동">
            <button class="tuning-secondary" id="asta-report-top" type="button">맨 위</button>
            <button class="tuning-secondary" id="asta-report-bottom" type="button">맨 아래</button>
          </div>
        </div>
        <pre id="asta-report-scroll" class="code-block tuning-report-scroll" tabindex="0">${escapeHtml(window.__astaLastReport.report)}</pre>
      </div>`;
    const reportScroller = document.getElementById("asta-report-scroll");
    document.getElementById("asta-report-top")?.addEventListener("click", () => reportScroller?.scrollTo({ top: 0, behavior: "smooth" }));
    document.getElementById("asta-report-bottom")?.addEventListener("click", () => reportScroller?.scrollTo({ top: reportScroller.scrollHeight, behavior: "smooth" }));
    requestAnimationFrame(() => {
      target.scrollIntoView({ block: "start", behavior: "smooth" });
      reportScroller?.focus({ preventScroll: true });
    });
    const downloadButton = document.getElementById("asta-download-report");
    if (downloadButton) downloadButton.hidden = false;
    const resetButton = document.getElementById("asta-reset");
    if (resetButton) resetButton.hidden = false;
  }

  /**
   * API 오류 객체에서 사용자에게 보여줄 메시지를 추출한다.
   */
  function errorDetailText(err) {
    const payload = err?.payload;
    const detail = payload?.detail;
    const queriedRunId = err?.queriedRunId || payload?.run_id || payload?.queried_run_id || "";
    const lines = [
      `메시지: ${err?.message || "알 수 없는 오류"}`,
      err?.status ? `HTTP 상태: ${err.status}` : "",
      err?.url ? `조회 endpoint: ${err.url}` : "",
      queriedRunId ? `조회 run_id: ${queriedRunId}` : "",
      payload?.error_code ? `ASTA 오류 코드: ${payload.error_code}` : "",
      detail?.error ? `서버 오류: ${detail.error}` : "",
      detail?.message ? `Oracle/상세: ${detail.message}` : "",
      payload ? `서버 응답:\n${JSON.stringify(payload, null, 2)}` : "",
    ].filter(Boolean);
    return lines.join("\n\n");
  }

  /**
   * ASTA 실행 오류를 화면의 오류 영역에 표시한다.
   */
  function renderError(target, err) {
    const detail = errorDetailText(err);
    window.__astaLastError = detail;
    target.innerHTML = `
      <div class="card stack" style="gap: var(--space-3); border-color:#fecaca; background:#fff7f7;">
        <div class="section-title" style="color:#b91c1c;">ASTA 호출 실패</div>
        <div style="color:#7f1d1d; line-height:1.55;">${escapeHtml(err?.message || "알 수 없는 오류")}</div>
        <div class="tuning-actions">
          <button class="tuning-secondary" id="asta-copy-error" type="button">오류 상세 클립보드 복사</button>
        </div>
        <div class="section-title">오류 상세</div>
        <pre class="code-block" style="white-space: pre-wrap; max-height: 420px; overflow:auto; border-color:#fecaca;">${escapeHtml(detail)}</pre>
      </div>`;
    const copyButton = document.getElementById("asta-copy-error");
    const resetButton = document.getElementById("asta-reset");
    if (resetButton) resetButton.hidden = false;
    if (copyButton) {
      copyButton.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(window.__astaLastError || detail);
          window.Toast?.show?.("오류 상세를 복사했습니다.", "success");
        } catch (_) {
          window.Toast?.show?.("복사 실패: 화면의 오류 상세를 직접 선택해서 복사하세요.", "error");
        }
      });
    }
  }

  /**
   * 진행 단계 코드를 UI 단계 순서 인덱스로 변환한다.
   */
  function progressStageIndex(step) {
    const seq = Number(step?.seq);
    if (Number.isInteger(seq) && seq >= 1 && seq <= DEFAULT_STEPS.length) return seq - 1;

    const code = String(step?.code || "").toUpperCase();
    const codeMap = {
      REQUEST_RECEIVED: 0,
      ORDS_DISPATCH: 1,
      SQL_GUARD: 2,
      BEFORE_EVIDENCE: 3,
      SQL_TUNING_ADVISOR: 4,
      VECTOR_KB: 5,
      LLM_REWRITE: 6,
      AFTER_EVIDENCE: 7,
      LLM_FINAL_REVIEW: 8,
      FINAL_REPORT: 9,
      VECTOR_SAVE: 10,
    };
    if (Object.prototype.hasOwnProperty.call(codeMap, code)) return codeMap[code];

    const raw = `${step.stage || ""} ${step.code || ""} ${step.label || ""} ${step.message || ""}`.toLowerCase();
    if (raw.includes("accepted") || raw.includes("request") || raw.includes("queued") || raw.includes("요청")) return 0;
    if (raw.includes("ords") || raw.includes("dispatch") || raw.includes("proxy") || raw.includes("호출")) return 1;
    if (raw.includes("guard") || raw.includes("safe") || raw.includes("안전")) return 2;
    if (raw.includes("sqltune") || raw.includes("advisor") || raw.includes("dbms_sqltune")) return 4;
    if (raw.includes("vector_save") || raw.includes("save_case") || raw.includes("auto_vector_save") || (raw.includes("vector") && (raw.includes("save") || raw.includes("저장")))) return 10;
    if (raw.includes("final_report") || raw.includes("report") || raw.includes("최종 보고서") || raw.includes("추천") || raw.includes("결과")) return 9;
    if (raw.includes("final_review") || raw.includes("second") || raw.includes("2차") || raw.includes("before/after")) return 8;
    if (raw.includes("candidate") || raw.includes("after") || raw.includes("equiv") || raw.includes("변경") || raw.includes("재수행") || raw.includes("비교")) return 7;
    if (raw.includes("genai_first") || raw.includes("first_pass") || raw.includes("rewrite") || raw.includes("1차") || raw.includes("후보")) return 6;
    if (raw.includes("vector") || raw.includes("similar") || raw.includes("유사")) return 5;
    if (raw.includes("baseline") || raw.includes("before") || raw.includes("원본") || raw.includes("xplan") || raw.includes("metrics")) return 3;
    return null;
  }

  /**
   * 서버 progress/steps 응답을 UI 렌더링에 맞는 단계 배열로 정규화한다.
   */
  function normalizeSteps(progress) {
    const incoming = Array.isArray(progress?.progress) ? progress.progress : Array.isArray(progress?.steps) ? progress.steps : [];
    if (!incoming.length) return DEFAULT_STEPS;
    const byIndex = DEFAULT_STEPS.map((step) => ({ ...step, status: "PENDING", detail: "대기", at: "", elapsed_ms: null }));
    incoming.forEach((rawStep, rawIndex) => {
      const mappedIndex = progressStageIndex(rawStep);
      const index = mappedIndex == null ? Math.min(rawIndex, DEFAULT_STEPS.length - 1) : mappedIndex;
      const base = DEFAULT_STEPS[index];
      byIndex[index] = {
        ...base,
        status: rawStep.status || byIndex[index].status || "PENDING",
        detail: rawStep.detail || rawStep.message || rawStep.label || byIndex[index].detail || "",
        at: rawStep.at || rawStep.started_at || rawStep.created_at || rawStep.updated_at || rawStep.completed_at || byIndex[index].at || "",
        elapsed_ms: rawStep.elapsed_ms ?? rawStep.duration_ms ?? rawStep.elapsedMs ?? byIndex[index].elapsed_ms ?? null,
      };
    });
    const progressedBeyondOrds = byIndex.slice(2).some((step) => {
      const status = String(step.status || "PENDING").toUpperCase();
      return status && status !== "PENDING";
    });
    if (progressedBeyondOrds && String(byIndex[1].status || "PENDING").toUpperCase() === "PENDING") {
      byIndex[1] = { ...byIndex[1], status: "DONE", detail: "ADB ORDS 분석 호출 완료" };
    }
    if (String(byIndex[7].status || "PENDING").toUpperCase() !== "PENDING" && String(byIndex[6].status || "PENDING").toUpperCase() === "PENDING") {
      byIndex[6] = { ...byIndex[6], status: "DONE", detail: "AI 1차 튜닝 완료" };
    }
    if (String(byIndex[10].status || "PENDING").toUpperCase() !== "PENDING" && String(byIndex[8].status || "PENDING").toUpperCase() === "PENDING") {
      byIndex[8] = { ...byIndex[8], status: "DONE", detail: "AI Before/After 정리 완료" };
    }
    const overall = String(progress?.status || "").toUpperCase();
    const doneStatuses = ["DONE", "COMPLETED", "SUCCESS", "ACCEPTED", "BASELINE_CAPTURED", "DBLINK_DEFERRED", "SKIPPED"];
    const failStatuses = ["FAILED", "ERROR", "WARN", "WARNING"];
    if (!overall || ["READY", "IDLE", "PENDING"].includes(overall)) {
      return byIndex;
    }
    if (["COMPLETED", "DONE", "BASELINE_CAPTURED"].includes(overall)) {
      return byIndex.map((step) => {
        const status = String(step.status || "PENDING").toUpperCase();
        if (failStatuses.includes(status)) return step;
        if (doneStatuses.includes(status)) return { ...step, status: "DONE", detail: step.detail && step.detail !== "대기" ? step.detail : "완료" };
        return step;
      });
    }
    let firstPendingSeen = false;
    return byIndex.map((step) => {
      const status = String(step.status || "PENDING").toUpperCase();
      if (doneStatuses.includes(status)) return { ...step, status: "DONE" };
      if (failStatuses.includes(status)) return step;
      if (!firstPendingSeen) { firstPendingSeen = true; return { ...step, status: "RUNNING", detail: step.detail && step.detail !== "대기" ? step.detail : "현재 실행 중" }; }
      return step;
    });
  }

  /**
   * ASTA 진행률 스택과 상태 배지를 화면에 그린다.
   */
  function renderProgressStack(target, progress) {
    const steps = normalizeSteps(progress);
    const statusText = progress?.status || "READY";
    const overall = String(statusText || "READY").toUpperCase();
    const running = steps.find((step) => String(step.status || "").toUpperCase() === "RUNNING");
    const failed = steps.find((step) => ["FAILED", "ERROR"].includes(String(step.status || "").toUpperCase()));
    const completedSteps = steps.filter((step) => ["DONE", "COMPLETED"].includes(String(step.status || "").toUpperCase()));
    const isOverallComplete = ["COMPLETED", "DONE", "BASELINE_CAPTURED"].includes(overall);
    const isOverallFailed = ["FAILED", "ERROR"].includes(overall);
    const current = isOverallComplete ? null : (running || failed || completedSteps[completedSteps.length - 1] || steps[0]);
    const currentStatus = isOverallComplete ? "COMPLETED" : String(current?.status || overall || "PENDING").toUpperCase();
    const isRunning = currentStatus === "RUNNING";
    const isFailed = !isOverallComplete && (["FAILED", "ERROR"].includes(currentStatus) || isOverallFailed);
    const isComplete = isOverallComplete;
    const ready = ["READY", "IDLE", "PENDING"].includes(overall) && !running && !failed && completedSteps.length === 0;
    const elapsed = !isOverallComplete && current?.elapsed_ms != null ? ` · ${formatDuration(current.elapsed_ms)}` : "";
    const totalElapsed = totalElapsedMs(progress, steps, isComplete);
    const totalElapsedText = !ready && totalElapsed != null ? `전체 ${formatDuration(totalElapsed)}` : "";
    const label = ready ? "대기 중" : isComplete ? "완료" : current?.label || statusText;
    const detail = isComplete ? "AI 분석이 종료되었습니다" : ready ? "SQL 입력 후 AI 분석 실행을 누르세요" : current?.detail || statusText;
    const dotClass = isFailed ? "failed" : isComplete ? "done" : isRunning ? "running" : "pending";
    target.innerHTML = `
      <div class="tuning-current-progress tuning-current-${escapeHtml(dotClass)}" title="현재 진행 단계와 전체 수행 시간을 표시합니다">
        <span class="tuning-current-label">현재 진행</span>
        <span class="tuning-current-dot" aria-hidden="true">${isRunning ? '<span class="tuning-spinner"></span>' : isComplete ? '✓' : isFailed ? '!' : ''}</span>
        <span class="tuning-current-main">${escapeHtml(label)}</span>
        <span class="tuning-current-detail">${escapeHtml([detail, elapsed].filter(Boolean).join(""))}</span>
        ${totalElapsedText ? `<span class="tuning-current-total">${escapeHtml(totalElapsedText)}</span>` : ""}
      </div>`;
  }

  /**
   * 현재 입력값에서 analyze 호출 URL을 만든다.
   */
  function buildAnalyzeUrl(input) {
    let trimmed = String(input || "").trim().replace(/\/+$/, "");
    if (/\/api\/asta(?:\/analyze)*$/i.test(trimmed)) {
      trimmed = DEFAULT_ORDS_BASE_URL;
    }
    trimmed = trimmed.replace(/\/ords\/asta\/api(?:\/analyze)*$/i, "/ords/admin/api");
    trimmed = trimmed.replace(/(?:\/analyze)+$/i, "");
    return `${trimmed}/analyze`;
  }

  /**
   * analyze URL에서 run 조회용 base URL을 계산한다.
   */
  function buildBaseUrl(input) {
    return buildAnalyzeUrl(input).replace(/\/analyze$/i, "");
  }

  /**
   * JSON API를 호출하고 HTTP/파싱 오류를 표준 오류로 변환한다.
   */
  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const text = await response.text();
    let data;
    try { data = JSON.parse(text); } catch (_) { data = { report: text }; }
    if (!response.ok) {
      const detail = data?.detail;
      const message = detail?.message || detail?.error || data?.message || data?.error || `HTTP ${response.status}`;
      const err = new Error(`${message} @ ${url}`);
      err.status = response.status;
      err.payload = data;
      throw err;
    }
    const bodyStatus = String(data?.status || "").toUpperCase();
    const errorCode = String(data?.error_code || data?.error?.code || "").toUpperCase();
    if (bodyStatus === "NOT_FOUND" || errorCode === "RUN_NOT_FOUND" || errorCode === "REPORT_NOT_FOUND") {
      const message = data?.message || data?.error?.message || errorCode || bodyStatus;
      const err = new Error(`${message} @ ${url}`);
      err.status = response.status;
      err.url = url;
      err.payload = data;
      const match = url.match(/\/runs\/([^/?#]+)/);
      if (match) err.queriedRunId = decodeURIComponent(match[1]);
      throw err;
    }
    return data;
  }

  /**
   * run_id 기준 ASTA 최종 리포트를 별도 조회한다.
   */
  async function fetchReport(baseUrl, runId) {
    const encodedRunId = encodeURIComponent(runId);
    const data = await fetchJson(`${baseUrl}/runs/${encodedRunId}/report`);
    return typeof data === "string" ? { report_markdown: data } : data;
  }

  /**
   * 서버 진행률이 없을 때 클라이언트 임시 progress 모델을 만든다.
   */
  function buildClientProgress(status, startedAt, stepIndex, stepStartedAt = startedAt, endedAt = null, detail = "") {
    const now = endedAt || new Date();
    const steps = DEFAULT_STEPS.map((step, index) => {
      if (index < stepIndex) return stepWithTiming(step, "DONE", "완료", now, null);
      if (index === stepIndex && status === "RUNNING") return stepWithTiming(step, "RUNNING", detail || "현재 실행 중", stepStartedAt, now - stepStartedAt);
      if (status === "COMPLETED") return stepWithTiming(step, "DONE", "완료", endedAt || now, null);
      if (status === "FAILED" && index === stepIndex) return stepWithTiming(step, "FAILED", detail || "실패", endedAt || now, now - stepStartedAt);
      return stepWithTiming(step, "PENDING", "대기", null, null);
    });
    return { status, startedAt, endedAt, totalDurationMs: now - startedAt, progress: steps };
  }

  /**
   * 비동기 ASTA run 진행률을 주기적으로 조회해 화면을 갱신한다.
   */
  async function pollRunProgress(baseUrl, runId, progressTarget, resultTarget) {
    const encodedRunId = encodeURIComponent(runId);
    const maxAttempts = 2400; // 40분: SQLTUNE/LLM final review 장시간 실행 허용
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const progress = await fetchJson(`${baseUrl}/runs/${encodedRunId}/progress`);
      const uiStartedAt = window.__astaRunStartedAt;
      const totalDurationMs = uiStartedAt instanceof Date ? Date.now() - uiStartedAt.getTime() : undefined;
      renderProgressStack(progressTarget, { ...progress, totalDurationMs });
      const status = String(progress?.status || "").toUpperCase();
      if (["COMPLETED", "DONE", "FAILED"].includes(status)) {
        if (status !== "FAILED") renderResult(resultTarget, await fetchReport(baseUrl, runId));
        return progress;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    try {
      const report = await fetchReport(baseUrl, runId);
      renderResult(resultTarget, report);
      renderProgressStack(progressTarget, { status: "COMPLETED", progress: DEFAULT_STEPS.map((step) => stepWithTiming(step, "DONE", "완료", new Date(), null)) });
      return { status: "COMPLETED", progress: DEFAULT_STEPS };
    } catch (err) {
      throw new Error(`진행 상태 확인 시간이 초과되었습니다. Run ID ${runId}는 계속 실행 중일 수 있습니다. 잠시 후 보고서 조회를 다시 시도하세요.`);
    }
  }

  /**
   * ASTA 튜닝 Assistant view 전체 DOM, 이벤트, API 흐름을 초기화한다.
   */
  window.Views.tuningAssistant = async function tuningAssistant() {
    const main = document.getElementById("main");
    main.innerHTML = `
      <style>
        .tuning-shell {
          --tuning-bg: #f7f8fb;
          --tuning-panel: #ffffff;
          --tuning-surface: #f3f6fb;
          --tuning-border: #dfe5ef;
          --tuning-text: #172033;
          --tuning-muted: #64748b;
          --tuning-accent: #2563eb;
          min-height: calc(100vh - 86px);
          margin: calc(var(--space-5) * -1);
          padding: clamp(18px, 2.4vw, 34px);
          color: var(--tuning-text);
          background:
            radial-gradient(circle at 12% 0%, rgba(37,99,235,0.13), transparent 30%),
            radial-gradient(circle at 88% 8%, rgba(14,165,233,0.12), transparent 28%),
            linear-gradient(135deg, #f7f8fb 0%, #ffffff 48%, #eef4ff 100%);
        }
        .tuning-hero {
          display:flex; align-items:flex-end; justify-content:space-between; gap:18px;
          margin-bottom:18px;
        }
        .tuning-kicker {
          display:inline-flex; align-items:center; gap:8px; margin-bottom:10px;
          color:#475569; font-size:12px; letter-spacing:.08em; text-transform:uppercase;
        }
        .tuning-dot { width:8px; height:8px; border-radius:999px; background:var(--tuning-accent); box-shadow:0 0 24px var(--tuning-accent); }
        .tuning-title { margin:0; font-size:clamp(30px, 4vw, 48px); line-height:1; letter-spacing:-1.05px; font-weight:590; }
        .tuning-subtitle { margin:12px 0 0; color:var(--tuning-muted); max-width:780px; line-height:1.6; }
        .tuning-grid { display:block; }
        .tuning-card {
          border:1px solid var(--tuning-border); border-radius:22px; padding:18px;
          background:#ffffff;
          box-shadow:0 20px 55px rgba(15,23,42,.10), inset 0 1px 0 rgba(255,255,255,.9);
          backdrop-filter: blur(12px);
        }
        .tuning-card-title { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px; font-weight:590; }
        .tuning-hero-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
        .tuning-top-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
        .tuning-current-progress { display:inline-flex; align-items:center; gap:8px; min-height:40px; max-width:min(680px, 100%); padding:8px 12px; border:1px solid #dbe3ef; border-radius:999px; background:#ffffff; color:#334155; box-shadow:0 8px 22px rgba(15,23,42,.07); }
        .tuning-current-label { color:#64748b; font-size:12px; font-weight:650; white-space:nowrap; }
        .tuning-current-dot { width:22px; height:22px; display:inline-grid; place-items:center; border-radius:999px; background:#eff6ff; color:#1d4ed8; font-size:12px; font-weight:700; flex:0 0 auto; }
        .tuning-current-running .tuning-current-dot { background:#eff6ff; }
        .tuning-current-done .tuning-current-dot { background:#dcfce7; color:#15803d; }
        .tuning-current-failed .tuning-current-dot { background:#fee2e2; color:#b91c1c; }
        .tuning-current-main { font-size:13px; font-weight:650; color:#172033; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:210px; }
        .tuning-current-detail { font-size:12px; color:#64748b; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:260px; }
        .tuning-current-total { margin-left:2px; padding:3px 8px; border-radius:999px; background:#eff6ff; color:#1d4ed8; font-size:12px; font-weight:700; white-space:nowrap; }
        .tuning-pill { color:#475569; border:1px solid #dbe3ef; border-radius:999px; padding:5px 10px; font-size:12px; background:#f8fafc; }
        .tuning-field { display:flex; flex-direction:column; gap:8px; margin-bottom:14px; }
        .tuning-field span { color:#475569; font-size:13px; font-weight:510; }
        .tuning-sql-wrap { position:relative; display:grid; grid-template-columns:52px minmax(0,1fr); border:1px solid #dbe3ef; border-radius:14px; overflow:hidden; background:#fbfdff; box-shadow:inset 0 0 0 1px rgba(255,255,255,.75), 0 1px 2px rgba(15,23,42,.04); }
        .tuning-line-numbers { padding:18px 10px; color:#94a3b8; background:#f1f5f9; border-right:1px solid #dbe3ef; text-align:right; user-select:none; white-space:pre; overflow:hidden; font-family:'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace; font-size:14px; line-height:1.62; }
        .tuning-input, .tuning-sql {
          width:100%; box-sizing:border-box; color:#0f172a; background:#fbfdff;
          border:1px solid #dbe3ef; border-radius:14px; outline:none;
          box-shadow:inset 0 0 0 1px rgba(255,255,255,.75), 0 1px 2px rgba(15,23,42,.04);
        }
        .tuning-sql-wrap .tuning-sql { border:0; border-radius:0; box-shadow:none; }
        .tuning-input { padding:12px 14px; }
        .tuning-sql {
          height: clamp(520px, calc(100vh - 360px), 820px);
          min-height: 460px;
          resize: vertical;
          padding:18px;
          font-family:'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
          font-size:14px; line-height:1.62; tab-size:2;
          display:block;
          overflow:auto;
          overflow-y:auto;
          overflow-x:auto;
          white-space:pre;
          -webkit-overflow-scrolling:touch;
        }
        .tuning-actions { display:flex; gap:10px; flex-wrap:wrap; }
        .tuning-primary {
          border:0; border-radius:12px; padding:12px 16px; color:white; cursor:pointer;
          background:linear-gradient(135deg, #1d4ed8, #3b82f6); font-weight:590;
          box-shadow:0 12px 28px rgba(37,99,235,.24);
        }
        .tuning-secondary { border:1px solid #dbe3ef; border-radius:12px; padding:12px 14px; color:#334155; background:#ffffff; cursor:pointer; }
        .tuning-secondary:hover { transform:translateY(-1px); box-shadow:0 10px 24px rgba(15,23,42,.08); }
        .tuning-aside { position:static; margin-top:18px; }
        .tuning-step { display:flex; gap:12px; padding:13px 0; border-top:1px solid #edf2f7; color:#64748b; line-height:1.5; }
        .tuning-step:first-of-type { border-top:0; }
        .tuning-step b { color:#172033; }
        .tuning-step-running { background:linear-gradient(90deg, rgba(37,99,235,.08), transparent); margin-inline:-8px; padding-inline:8px; border-radius:12px; }
        .tuning-step-done .tuning-num, .tuning-step-completed .tuning-num { background:#dcfce7; color:#15803d; }
        .tuning-step-failed .tuning-num, .tuning-step-error .tuning-num { background:#fee2e2; color:#b91c1c; }
        .tuning-run-meta { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:8px 0 14px; padding:12px; border:1px solid #e2e8f0; border-radius:14px; background:#f8fafc; }
        .tuning-run-meta div { display:flex; flex-direction:column; gap:3px; min-width:0; }
        .tuning-run-meta b { font-size:11px; color:#64748b; font-weight:600; }
        .tuning-run-meta span { font-size:12px; color:#172033; display:inline-flex; align-items:center; gap:6px; }
        .tuning-spinner { width:14px; height:14px; border:2px solid #bfdbfe; border-top-color:#2563eb; border-radius:50%; display:inline-block; animation:tuning-spin .8s linear infinite; }
        @keyframes tuning-spin { to { transform:rotate(360deg); } }
        .tuning-num { flex:0 0 26px; height:26px; display:grid; place-items:center; border-radius:9px; background:#eff6ff; color:#1d4ed8; font-size:12px; }
        .tuning-result { margin-top:18px; }
        .tuning-report-card { min-height: min(82vh, 980px); }
        .tuning-report-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; }
        .tuning-report-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
        .tuning-report-scroll {
          white-space:pre;
          height:min(74vh, 900px);
          min-height:520px;
          max-height:calc(100dvh - 180px);
          overflow:auto;
          resize:vertical;
          overscroll-behavior:contain;
          scroll-behavior:smooth;
          -webkit-overflow-scrolling:touch;
        }
        .tuning-report-scroll:focus { outline:2px solid rgba(37,99,235,.28); outline-offset:2px; }
        @media (max-width: 1100px) { .tuning-grid { grid-template-columns:1fr; } .tuning-aside { position:static; } }
        @media (max-width: 720px) {
          .tuning-shell {
            min-height: calc(100dvh - 56px);
            margin: calc(var(--space-3, 12px) * -1);
            padding: 12px;
            background: #f7f8fb;
          }
          .tuning-hero {
            display:block;
            margin-bottom:12px;
          }
          .tuning-hero-actions, .tuning-top-actions { justify-content:flex-start; margin-top:8px; }
          .tuning-current-progress { width:100%; justify-content:flex-start; border-radius:14px; }
          .tuning-current-main { max-width:38vw; }
          .tuning-current-detail { max-width:42vw; }
          .tuning-kicker { font-size:11px; margin-bottom:8px; }
          .tuning-title {
            font-size: 28px;
            line-height: 1.08;
            letter-spacing: -0.6px;
          }
          .tuning-subtitle {
            margin-top:8px;
            font-size:13px;
            line-height:1.45;
          }
          .tuning-hero > .tuning-pill { display:none; }
          .tuning-grid { gap:12px; }
          .tuning-card {
            border-radius:16px;
            padding:12px;
            box-shadow:0 10px 26px rgba(15,23,42,.08);
          }
          .tuning-card-title { margin-bottom:10px; }
          .tuning-card-title .tuning-pill { display:none; }
          .tuning-field { gap:6px; margin-bottom:10px; }
          .tuning-field span { font-size:12px; }
          .tuning-input { padding:10px 11px; font-size:14px; }
          .tuning-sql-wrap {
            grid-template-columns: 1fr;
            border-radius:12px;
            overflow: visible;
          }
          .tuning-line-numbers {
            display:none;
          }
          .tuning-sql {
            height: 58dvh;
            min-height: 360px;
            max-height: none;
            padding:12px;
            font-size:12.5px;
            line-height:1.55;
            overflow:auto;
            -webkit-overflow-scrolling:touch;
          }
          .tuning-actions {
            display:grid;
            grid-template-columns:1fr;
            gap:8px;
          }
          .tuning-primary,
          .tuning-secondary {
            width:100%;
            min-height:44px;
            padding:11px 12px;
          }
          .tuning-aside {
            position:static;
          }
          .tuning-run-meta {
            grid-template-columns:1fr 1fr;
            gap:6px;
            padding:9px;
            margin-bottom:8px;
          }
          .tuning-run-meta b { font-size:10px; }
          .tuning-run-meta span { font-size:11px; }
          .tuning-step {
            gap:9px;
            padding:9px 0;
            font-size:12px;
            line-height:1.35;
          }
          .tuning-num {
            flex-basis:22px;
            width:22px;
            height:22px;
            border-radius:7px;
            font-size:11px;
          }
          .tuning-result { margin-top:12px; }
          .tuning-result .card { padding:12px !important; border-radius:16px; }
          .tuning-result .code-block {
            max-height: 62vh !important;
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap !important;
            overflow-wrap: anywhere;
          }
          .tuning-report-head { display:grid; grid-template-columns:1fr; }
          .tuning-report-actions { display:grid; grid-template-columns:1fr 1fr; width:100%; }
          .tuning-report-scroll {
            height:68dvh;
            min-height:440px;
            max-height:68dvh !important;
            white-space:pre-wrap !important;
            overflow-wrap:anywhere;
          }
        }
        @media (max-width: 390px) and (orientation: portrait) {
          .tuning-shell {
            min-height: calc(100dvh - 50px);
            margin: -10px;
            padding: 10px;
          }
          .tuning-hero { margin-bottom: 10px; }
          .tuning-kicker { display:none; }
          .tuning-title { font-size: 24px; line-height: 1.05; letter-spacing: -0.45px; }
          .tuning-subtitle { font-size: 12px; line-height: 1.38; margin-top: 6px; }
          .tuning-card { padding: 10px; border-radius: 14px; }
          .tuning-card-title { font-size: 14px; margin-bottom: 8px; }
          .tuning-field { margin-bottom: 8px; }
          .tuning-input { padding: 9px 10px; font-size: 13px; }
          .tuning-sql-wrap { grid-template-columns: 1fr; border-radius: 10px; overflow: visible; }
          .tuning-line-numbers { display:none; }
          .tuning-sql {
            height: 60dvh;
            min-height: 340px;
            max-height: none;
            padding: 10px;
            font-size: 12px;
            line-height: 1.48;
          }
          .tuning-primary, .tuning-secondary { min-height: 42px; padding: 10px 11px; }
          .tuning-aside { max-height: 32dvh; overflow:auto; }
          .tuning-run-meta { grid-template-columns: 1fr 1fr; padding: 8px; }
          .tuning-step { padding: 7px 0; font-size: 11.5px; }
          .tuning-result .code-block { max-height: 56dvh !important; font-size: 11.5px; }
        }
        @media (max-height: 430px) and (orientation: landscape) {
          .tuning-shell {
            min-height: calc(100dvh - 46px);
            margin: -8px;
            padding: 8px;
          }
          .tuning-hero { display:none; }
          .tuning-grid { grid-template-columns: 1fr; gap: 8px; }
          .tuning-card { padding: 9px; border-radius: 12px; }
          .tuning-card-title { margin-bottom: 7px; font-size: 13px; }
          .tuning-field { gap: 5px; margin-bottom: 7px; }
          .tuning-field span { font-size: 11px; }
          .tuning-input { padding: 8px 9px; font-size: 12px; }
          .tuning-sql-wrap { grid-template-columns: 1fr; overflow: visible; }
          .tuning-line-numbers { display:none; }
          .tuning-sql {
            height: calc(100dvh - 190px);
            min-height: 170px;
            max-height: none;
            padding: 9px;
            font-size: 11.5px;
            line-height: 1.42;
          }
          .tuning-actions { grid-template-columns: 1fr 1fr; gap: 6px; }
          .tuning-primary, .tuning-secondary { min-height: 38px; padding: 8px 9px; font-size: 12px; }
          .tuning-aside { position: static; max-height: calc(100dvh - 62px); overflow:auto; }
          .tuning-run-meta { grid-template-columns: 1fr; gap: 4px; padding: 7px; margin-bottom: 6px; }
          .tuning-step { padding: 6px 0; gap: 7px; font-size: 11px; line-height: 1.25; }
          .tuning-num { flex-basis: 20px; width: 20px; height: 20px; font-size: 10px; }
          .tuning-result .code-block { max-height: 58dvh !important; font-size: 11px; }
        }
      </style>
      <section class="tuning-shell">
        <div class="tuning-hero">
          <div>
            <div class="tuning-kicker"><span class="tuning-dot"></span> ASTA Workspace</div>
            <h1 class="tuning-title">AI SQL Tuning Assistant</h1>
          </div>
          <div class="tuning-hero-actions">
            <div class="tuning-top-actions" aria-label="ASTA 빠른 작업">
              <button class="tuning-primary" id="asta-run" title="SQL Formatting 후 ADB ORDS/PLSQL AI 분석을 실행합니다">AI 분석 실행</button>
              <button class="tuning-secondary" id="asta-reset" type="button" hidden>신규분석(초기화)</button>
              <button class="tuning-secondary" id="asta-download-report" type="button" hidden>보고서 다운로드</button>
              <button class="tuning-secondary tuning-secret-only" id="asta-sql-only-llm" type="button" hidden title="SQL 텍스트만 선택한 LLM profile로 전송합니다">SQL만 LLM</button>
              <span id="asta-current-progress" class="tuning-progress-anchor" aria-live="polite"></span>
            </div>
          </div>
        </div>

        <div class="tuning-grid">
          <div class="tuning-card">
            <div class="tuning-card-title">
              <span>SQL 분석 입력</span>
            </div>
            <label class="tuning-field">
              <span>AI Profile</span>
              <select class="tuning-input" id="asta-ai-profile">
                <option value="ASTA_GPT5_PROFILE" selected>ASTA_GPT5_PROFILE</option>
                <option value="ASTA_GROK_GENAI_PROFILE">ASTA_GROK_GENAI_PROFILE</option>
                <option value="ASTA_DB_GENAI_TEST">ASTA_DB_GENAI_TEST</option>
              </select>
            </label>
            <label class="tuning-field">
              <span>샘플 튜닝대상 SQL</span>
              <select class="tuning-input" id="asta-sample-sql">
                <option value="">직접 입력</option>
                ${ASTA_SAMPLE_SQLS.map((sample) => `<option value="${escapeHtml(sample.id)}">${escapeHtml(sample.label)}</option>`).join("")}
              </select>
            </label>
            <label class="tuning-field">
              <span>LLM 참고사항 (선택)</span>
              <textarea class="tuning-input tuning-notes" id="asta-tuning-notes" rows="4" spellcheck="false" placeholder="예: 특정 테이블/인덱스/조건을 중점 검토, 업무상 유지해야 하는 조건, 의심 병목 등"></textarea>
            </label>
            <label class="tuning-field">
              <span>SQL</span>
              <textarea class="tuning-sql" id="asta-sql" rows="18" spellcheck="false" placeholder="SELECT ...">select * from dual</textarea>
            </label>
          </div>
        </div>

        <div id="asta-result" class="tuning-result stack"></div>
      </section>`;

    const profileInput = document.getElementById("asta-ai-profile");
    const sampleInput = document.getElementById("asta-sample-sql");
    const notesInput = document.getElementById("asta-tuning-notes");
    const sqlInput = document.getElementById("asta-sql");
    const lineNumbers = document.getElementById("asta-line-numbers");
    const result = document.getElementById("asta-result");
    const progressTarget = document.getElementById("asta-current-progress");
    renderProgressStack(progressTarget, { status: "READY", progress: DEFAULT_STEPS });

    /**
     * SQL 입력/결과/진행률/옵션을 기본 상태로 초기화한다.
     */
    function resetWorkspace() {
      const runButton = document.getElementById("asta-run");
      const resetButton = document.getElementById("asta-reset");
      const downloadButton = document.getElementById("asta-download-report");
      window.__astaLastReport = null;
      window.__astaLastError = null;
      window.__astaRunStartedAt = null;
      result.innerHTML = "";
      renderProgressStack(progressTarget, { status: "READY", progress: DEFAULT_STEPS });
      if (runButton) {
        runButton.disabled = false;
        runButton.textContent = "AI 분석 실행";
      }
      if (resetButton) resetButton.hidden = true;
      if (downloadButton) downloadButton.hidden = true;
    }

    /**
     * ADB ORDS에서 선택 가능한 ASTA LLM 프로필 목록을 불러온다.
     */
    async function loadAstaProfiles() {
      try {
        const data = await fetchJson("/api/asta/profiles");
        const profiles = Array.isArray(data) ? data : (data.profiles || []);
        const astaProfiles = profiles
          .map((profile) => ({
            name: String(profile.profile_name || profile.name || "").trim(),
            label: String(profile.display_name || profile.profile_name || profile.name || "").trim(),
            model: String(profile.model || profile.model_name || "").trim(),
            provider: String(profile.provider || "").trim(),
            selectable: profile.selectable !== false,
            isDefault: profile.default === true || String(profile.profile_name || profile.name || "") === String(data.asta_default || ""),
          }))
          .filter((profile) => profile.name.toUpperCase().startsWith("ASTA") && profile.selectable)
          .sort((a, b) => a.name.localeCompare(b.name));
        if (!astaProfiles.length) return;
        const preferredProfile = astaProfiles.find((profile) => profile.name === DEFAULT_AI_PROFILE)
          || astaProfiles.find((profile) => profile.isDefault)
          || astaProfiles[0];
        profileInput.innerHTML = astaProfiles.map((profile) => {
          const meta = [profile.provider, profile.model].filter(Boolean).join(" / ");
          const text = meta ? `${profile.name} — ${meta}` : profile.name;
          return `<option value="${escapeHtml(profile.name)}" ${profile.name === preferredProfile.name ? "selected" : ""}>${escapeHtml(text)}</option>`;
        }).join("");
        if (!astaProfiles.some((profile) => profile.name === profileInput.value)) {
          profileInput.value = preferredProfile.name;
        }
      } catch (err) {
        console.warn("ASTA profile load failed", err);
        window.Toast?.show?.("ASTA profile 조회 실패: 기본 목록을 사용합니다.", "error");
      }
    }

    loadAstaProfiles();

    /**
     * 샘플 ID에 해당하는 ASTA 테스트 SQL을 에디터에 채운다.
     */
    function applySampleSql(sampleId) {
      const sample = ASTA_SAMPLE_SQLS.find((item) => item.id === sampleId);
      if (!sample) return;
      sqlInput.value = sample.sql;
      updateLineNumbers();
      window.Toast?.show?.("샘플 SQL을 입력창에 반영했습니다.", "success");
    }

    /**
     * SQL 에디터 줄 번호 영역을 갱신한다.
     */
    function updateLineNumbers() {}
    /**
     * SQL 에디터 스크롤과 줄 번호 스크롤을 동기화한다.
     */
    function syncLineNumberScroll() {}
    /**
     * SQL 에디터 표시 상태와 줄 번호를 다시 그린다.
     */
    function refreshSqlEditorPaint() {
      window.requestAnimationFrame(() => {
        sqlInput.style.transform = "translateZ(0)";
      });
    }
    sqlInput.addEventListener("input", refreshSqlEditorPaint);
    sampleInput.addEventListener("change", () => applySampleSql(sampleInput.value));

    document.getElementById("asta-download-report").addEventListener("click", () => {
      if (!window.__astaLastReport?.report) return;
      const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
      downloadText(`asta_tuning_report_${stamp}_${window.__astaLastReport.runId || "report"}.md`, window.__astaLastReport.report);
    });
    document.getElementById("asta-reset").addEventListener("click", resetWorkspace);

    document.addEventListener("keydown", (event) => {
      if (event.ctrlKey && event.altKey && String(event.key || "").toLowerCase() === "l") {
        const secretButton = document.getElementById("asta-sql-only-llm");
        if (secretButton) {
          secretButton.hidden = !secretButton.hidden;
          window.Toast?.show?.(secretButton.hidden ? "숨김 LLM 기능을 닫았습니다." : "숨김 기능: SQL만 LLM 버튼을 열었습니다.", "success");
        }
      }
    });

    document.getElementById("asta-sql-only-llm").addEventListener("click", async () => {
      const sql = sqlInput.value.trim();
      if (!sql) {
        window.Toast?.show?.("SQL을 입력하세요.", "error");
        return;
      }
      const startedAt = new Date();
      window.__astaRunStartedAt = startedAt;
      renderProgressStack(progressTarget, buildClientProgress("RUNNING", startedAt, 6, startedAt, null, "SQL 텍스트만 LLM으로 전송 중"));
      result.innerHTML = '<div class="empty-state"><span class="tuning-spinner"></span> SQL만 LLM으로 전송 중...</div>';
      try {
        const oracleSqlOnlyPrompt = [
          "Oracle Database 기준으로 SQL 튜닝을 요청합니다.",
          "아래 SQL을 Oracle 옵티마이저 관점에서 분석하고, 실행 가능한 개선 SQL을 제안하세요.",
          "DML/DDL/PLSQL은 제안하지 말고 SELECT/WITH 단일문만 제안하세요.",
          "힌트만 추가하는 것보다 구조적 rewrite가 가능하면 우선 제안하세요.",
          "응답에는 병목 추정, 변경 이유, 개선 SQL, 주의사항을 한국어로 포함하세요.",
          "SQL:",
          sql,
        ].join("\n");
        const data = await fetchJson(`${DEFAULT_ORDS_BASE_URL}/llm-sql-only`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sql,
            sql_text: sql,
            prompt: oracleSqlOnlyPrompt,
            user_prompt: oracleSqlOnlyPrompt,
            tuning_context: {
              mode: "SQL_ONLY_LLM",
              database: "Oracle Database",
              instruction: "Oracle 기준 SQL 튜닝 요청. SELECT/WITH 단일문 개선 SQL과 병목/변경 이유/주의사항을 한국어로 반환.",
            },
            ai_profile: profileInput.value || DEFAULT_AI_PROFILE,
            llm_profile: profileInput.value || DEFAULT_AI_PROFILE,
          }),
        });
        const endedAt = new Date();
        renderProgressStack(progressTarget, buildClientProgress("COMPLETED", startedAt, DEFAULT_STEPS.length - 1, startedAt, endedAt, "SQL-only LLM 완료"));
        renderResult(result, {
          ...data,
          run_id: `SQL_ONLY_${endedAt.toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}`,
          detailed_report_markdown: data.report_markdown || data.response || JSON.stringify(data, null, 2),
        });
      } catch (err) {
        const failedAt = new Date();
        renderError(result, err);
        renderProgressStack(progressTarget, buildClientProgress("FAILED", startedAt, 6, startedAt, failedAt, err.message));
        window.Toast?.show?.("SQL-only LLM 실패: " + err.message, "error", 15000);
      }
    });

    document.getElementById("asta-run").addEventListener("click", async () => {
      const runButton = document.getElementById("asta-run");
      const baseUrl = buildBaseUrl(DEFAULT_ENDPOINT);
      const url = buildAnalyzeUrl(DEFAULT_ENDPOINT);
      const sql = sqlInput.value.trim();
      const userNotes = (notesInput?.value || "").trim();
      const formattedSql = formatSql(sql);
      if (!sql) {
        window.Toast?.show?.("SQL을 입력하세요.", "error");
        return;
      }
      sqlInput.value = formattedSql;
      updateLineNumbers();
      const startedAt = new Date();
      window.__astaRunStartedAt = startedAt;
      let stepStartedAt = startedAt;
      let stepIndex = 0;
      const stepDetails = [
        "요청 수신",
        "ADB ORDS/PLSQL 동기 분석 실행 중 — 세부 단계별 이력은 완료 후 실제 DB progress로 표시됩니다",
        "SQL 안전성 검사",
        "원본 SQL Evidence 수집: metrics, SQL_ID, XPLAN, object 통계",
        "Tuning Advisor 수행",
        "ADB Vector KB 유사 결과서 조회",
        "AI 1차 튜닝: 분석결과 + Vector 사례 참조",
        "튜닝 SQL 분석: 튜닝 SQL 재수행/비교",
        "AI Before/After 정리",
        "최종 보고서 생성",
        "ADB Vector KB 결과서 저장",
      ];
      runButton.disabled = true;
      runButton.textContent = "분석중";
      const progressTimer = window.setInterval(() => {
        const elapsed = Date.now() - startedAt.getTime();
        const nextIndex = 1;
        if (nextIndex !== stepIndex) {
          stepIndex = nextIndex;
          stepStartedAt = new Date();
        }
        renderProgressStack(progressTarget, buildClientProgress("RUNNING", startedAt, stepIndex, stepStartedAt, null, stepDetails[stepIndex]));
      }, 500);
      renderProgressStack(progressTarget, buildClientProgress("RUNNING", startedAt, 0, stepStartedAt, null, stepDetails[0]));
      result.innerHTML = '<div class="empty-state"><span class="tuning-spinner"></span> ADB ORDS/PLSQL 기반 AI 분석 실행 중...</div>';
      let completedOk = false;
      try {
        const sourceId = DEFAULT_SOURCE_ID;
        const data = await fetchJson(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sql_text: formattedSql,
            sql: formattedSql,
            source_db_id: sourceId,
            ai_profile: profileInput.value || DEFAULT_AI_PROFILE,
            llm_profile: profileInput.value || DEFAULT_AI_PROFILE,
            use_llm: true,
            run_advisor: true,
            use_sqltune: true,
            sqltune_time_limit: 1800,
            tuning_context: {
              user_notes: userNotes,
              source: "UI_OPTIONAL_TEXT",
              instruction: userNotes ? "사용자 참고사항을 SQL 튜닝 후보 생성과 최종 결과서 판단에 우선 참고하되, 실제 실행 evidence와 충돌하면 evidence를 우선한다." : "",
            },
            options: {
              fetch_rows: 100,
              timeout_seconds: 900,
              sqltune_time_limit: 1800,
              run_advisor: true,
              use_sqltune: true,
              run_mode: "ASYNC",
              use_llm: true,
              llm_profile: profileInput.value || DEFAULT_AI_PROFILE,
            },
          }),
        });
        window.clearInterval(progressTimer);
        if (data?.run_id && ["RUNNING", "QUEUED"].includes(String(data?.status || "").toUpperCase())) {
          await pollRunProgress(baseUrl, data.run_id, progressTarget, result);
        } else {
          const endedAt = new Date();
          let finalProgress = null;
          const proxySource = String(data?.proxy?.source || "").toUpperCase();
          const hasAuthoritativeInlineProgress = proxySource.includes("SOURCE_DIRECT_FALLBACK") || proxySource.includes("CONTROLLED_FALLBACK");
          if (data?.run_id && !hasAuthoritativeInlineProgress) {
            const encodedRunId = encodeURIComponent(data.run_id);
            try { finalProgress = await fetchJson(`${baseUrl}/runs/${encodedRunId}/progress`); } catch (_) { finalProgress = null; }
          } else if (data?.run_id && hasAuthoritativeInlineProgress) {
            console.warn("asta-progress-stale-ords-suppressed", {
              run_id: data.run_id,
              proxy_source: data?.proxy?.source || "",
              inline_status: data?.status || "",
            });
          }
          if (finalProgress?.progress || finalProgress?.steps) {
            renderProgressStack(progressTarget, { ...finalProgress, status: "COMPLETED", startedAt, endedAt, totalDurationMs: endedAt - startedAt });
          } else if (data?.progress || data?.steps) {
            renderProgressStack(progressTarget, { ...data, status: "COMPLETED", startedAt, endedAt, totalDurationMs: endedAt - startedAt });
          } else {
            renderProgressStack(progressTarget, buildClientProgress("COMPLETED", startedAt, DEFAULT_STEPS.length - 1, stepStartedAt, endedAt, "완료"));
          }
          renderResult(result, data);
        }
        runButton.textContent = "완료";
        completedOk = true;
        window.Toast?.show?.("ASTA 분석이 완료되었습니다.", "success");
      } catch (err) {
        window.clearInterval(progressTimer);
        const failedAt = new Date();
        renderError(result, err);
        renderProgressStack(progressTarget, buildClientProgress("FAILED", startedAt, stepIndex, stepStartedAt, failedAt, err.message));
        runButton.textContent = "실패";
        window.Toast?.show?.("ASTA 호출 실패: " + err.message, "error", 15000);
      } finally {
        if (!completedOk) runButton.disabled = false;
      }
    });
  };
})();
