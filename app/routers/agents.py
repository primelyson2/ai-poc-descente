"""기능요구사항02 (메뉴 [3] AI Agent Team Test) — 실제 DB 호출.

조회:
- /agents/teams                                    팀 목록
- /agents/teams/{name}                             팀 상세 (Agents + Tasks)
- /agents/{name}, /agents/tasks/{name}, /agents/tools/{name}  속성 그리드용 상세

실행:
- POST /agents/teams/run                           CREATE_CONVERSATION + RUN_TEAM (CLOB OUT)
- GET  /agents/conversations/{conv_id}/timeline    실행 이력 기반 단계별 타임라인 + raw 로그

스키마 메모 (ailakehouse 실제 컬럼 기준):
  USER_AI_AGENT_TEAMS         AGENT_TEAM_ID, AGENT_TEAM_NAME, STATUS, DESCRIPTION (CLOB)
  USER_AI_AGENT_TEAM_ATTRIBUTES   ATTRIBUTE_NAME='agents' → JSON [{"name":"A","task":"T"}]
                                  ATTRIBUTE_NAME='process'
  USER_AI_AGENT_TEAM_HISTORY  TEAM_EXEC_ID, TEAM_NAME, STATE, START_DATE, END_DATE, CONVERSATION_ID
  USER_AI_AGENTS              AGENT_ID, AGENT_NAME, STATUS, DESCRIPTION
  USER_AI_AGENT_ATTRIBUTES    'profile_name', 'role' 등
  USER_AI_AGENT_TASKS         TASK_ID, TASK_NAME
  USER_AI_AGENT_TASK_ATTRIBUTES   'tools' → JSON ["TOOL", ...], 'instruction', 'input'
  USER_AI_AGENT_TASK_HISTORY  TEAM_EXEC_ID, TASK_ORDER, AGENT_NAME, TASK_NAME, STATE, START_DATE, END_DATE
  USER_AI_AGENT_TOOLS         TOOL_ID, TOOL_NAME
  USER_AI_AGENT_TOOL_ATTRIBUTES
  USER_AI_AGENT_TOOL_HISTORY  INVOCATION_ID, TEAM_EXEC_ID, TASK_ORDER, TOOL_NAME, AGENT_NAME, TASK_NAME,
                              START_DATE, END_DATE
  USER_CLOUD_AI_CONVERSATION_PROMPTS  CONVERSATION_PROMPT_ID, CONVERSATION_ID, PROFILE_NAME,
                              PROMPT_ACTION, PROMPT (CLOB), PROMPT_RESPONSE (CLOB), CREATED
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import oracledb
from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import build_run_team_block, first_line as _first_line, read_clob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


def _safe_parse_json(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ====================================================================
# 조회: 트리
# ====================================================================

@router.get("/teams")
async def list_teams(database: str = Depends(current_db)) -> list[dict]:
    return await db.fetch_all(
        database,
        "SELECT agent_team_name AS name, status, description "
        "FROM USER_AI_AGENT_TEAMS ORDER BY agent_team_name",
    )


# 트리 한 번에 — 5개 쿼리 병렬 실행으로 N×roundtrip 회피
@router.get("/tree")
async def tree(database: str = Depends(current_db)) -> dict:
    teams_rows, team_attr_rows, agent_rows, task_rows, tool_rows = await asyncio.gather(
        db.fetch_all(
            database,
            "SELECT agent_team_name AS name, status, description "
            "FROM USER_AI_AGENT_TEAMS ORDER BY agent_team_name",
        ),
        db.fetch_all(
            database,
            "SELECT agent_team_name AS team_name, attribute_value "
            "FROM USER_AI_AGENT_TEAM_ATTRIBUTES WHERE attribute_name = 'agents'",
        ),
        db.fetch_all(
            database,
            "SELECT agent_name, attribute_name, attribute_value "
            "FROM USER_AI_AGENT_ATTRIBUTES "
            "WHERE attribute_name IN ('role', 'profile_name')",
        ),
        db.fetch_all(
            database,
            "SELECT task_name, attribute_name, attribute_value "
            "FROM USER_AI_AGENT_TASK_ATTRIBUTES "
            "WHERE attribute_name IN ('tools', 'instruction')",
        ),
        db.fetch_all(
            database,
            "SELECT tool_name, attribute_name, attribute_value "
            "FROM USER_AI_AGENT_TOOL_ATTRIBUTES "
            "WHERE attribute_name IN ('tool_type', 'instruction')",
        ),
    )

    team_agents_raw = {r["team_name"]: r["attribute_value"] for r in team_attr_rows}

    agent_attr_map: dict[str, dict] = {}
    for r in agent_rows:
        agent_attr_map.setdefault(r["agent_name"], {})[r["attribute_name"]] = r["attribute_value"]

    task_attr_map: dict[str, dict] = {}
    for r in task_rows:
        task_attr_map.setdefault(r["task_name"], {})[r["attribute_name"]] = r["attribute_value"]

    tool_attr_map: dict[str, dict] = {}
    for r in tool_rows:
        tool_attr_map.setdefault(r["tool_name"], {})[r["attribute_name"]] = r["attribute_value"]

    teams_out: list[dict] = []
    for t in teams_rows:
        name = t["name"]
        agents_json = _safe_parse_json(team_agents_raw.get(name)) or []
        agents: list[dict] = []
        seen_task: set[str] = set()
        task_names: list[str] = []
        for item in agents_json if isinstance(agents_json, list) else []:
            if not isinstance(item, dict):
                continue
            a_name = item.get("name") or ""
            task = item.get("task") or ""
            am = agent_attr_map.get(a_name, {})
            agents.append({
                "name": a_name,
                "tasks": [task] if task else [],
                "role": am.get("role") or "",
                "profile_name": am.get("profile_name") or "",
            })
            if task and task not in seen_task:
                seen_task.add(task)
                task_names.append(task)

        tasks: list[dict] = []
        for tn in task_names:
            tm = task_attr_map.get(tn, {})
            tools_val = _safe_parse_json(tm.get("tools"))
            tools = [str(x) for x in tools_val] if isinstance(tools_val, list) else []
            tasks.append({
                "name": tn,
                "tools": tools,
                "instruction": tm.get("instruction") or "",
            })

        teams_out.append({
            "name": name,
            "status": t.get("status"),
            "description": t.get("description") or "",
            "agents": agents,
            "tasks": tasks,
        })

    tools_meta = {
        n: {
            "tool_type": m.get("tool_type") or "",
            "instruction": m.get("instruction") or "",
        }
        for n, m in tool_attr_map.items()
    }
    return {"teams": teams_out, "tools_meta": tools_meta}


@router.get("/teams/{name}")
async def team_detail(name: str, database: str = Depends(current_db)) -> dict:
    """팀 상세 — 상세 패널용 head + attributes 만.

    트리 빌딩(agents/tasks/tools_meta)은 /api/agents/tree 가 담당한다.
    """
    head_rows, attr_rows = await asyncio.gather(
        db.fetch_all(
            database,
            "SELECT agent_team_name, status, description "
            "FROM USER_AI_AGENT_TEAMS WHERE agent_team_name = :name",
            name=name,
        ),
        db.fetch_all(
            database,
            "SELECT attribute_name, attribute_value FROM USER_AI_AGENT_TEAM_ATTRIBUTES "
            "WHERE agent_team_name = :name ORDER BY attribute_name",
            name=name,
        ),
    )
    if not head_rows:
        raise HTTPException(status_code=404, detail={"error": "team not found", "team": name})
    head = head_rows[0]
    return {
        "name": head["agent_team_name"],
        "status": head.get("status"),
        "description": head.get("description") or "",
        "attributes": attr_rows,
    }


@router.get("/{name}")
async def agent_detail(name: str, database: str = Depends(current_db)) -> dict:
    head_rows, attrs = await asyncio.gather(
        db.fetch_all(
            database,
            "SELECT agent_name, status, description FROM USER_AI_AGENTS WHERE agent_name = :name",
            name=name,
        ),
        db.fetch_all(
            database,
            "SELECT attribute_name, attribute_value FROM USER_AI_AGENT_ATTRIBUTES "
            "WHERE agent_name = :name ORDER BY attribute_name",
            name=name,
        ),
    )
    head = head_rows[0] if head_rows else {"agent_name": name, "status": None, "description": ""}
    return {
        "name": head.get("agent_name"),
        "status": head.get("status"),
        "description": head.get("description") or "",
        "attributes": attrs,
    }


@router.get("/tasks/{name}")
async def task_detail(name: str, database: str = Depends(current_db)) -> dict:
    head_rows, attrs = await asyncio.gather(
        db.fetch_all(
            database,
            "SELECT task_name, status, description FROM USER_AI_AGENT_TASKS WHERE task_name = :name",
            name=name,
        ),
        db.fetch_all(
            database,
            "SELECT attribute_name, attribute_value FROM USER_AI_AGENT_TASK_ATTRIBUTES "
            "WHERE task_name = :name ORDER BY attribute_name",
            name=name,
        ),
    )
    head = head_rows[0] if head_rows else {"task_name": name, "status": None, "description": ""}
    return {
        "name": head.get("task_name"),
        "status": head.get("status"),
        "description": head.get("description") or "",
        "attributes": attrs,
    }


@router.get("/tools/{name}")
async def tool_detail(name: str, database: str = Depends(current_db)) -> dict:
    head_rows, attrs = await asyncio.gather(
        db.fetch_all(
            database,
            "SELECT tool_name, status, description FROM USER_AI_AGENT_TOOLS WHERE tool_name = :name",
            name=name,
        ),
        db.fetch_all(
            database,
            "SELECT attribute_name, attribute_value FROM USER_AI_AGENT_TOOL_ATTRIBUTES "
            "WHERE tool_name = :name ORDER BY attribute_name",
            name=name,
        ),
    )
    head = head_rows[0] if head_rows else {"tool_name": name, "status": None, "description": ""}
    return {
        "name": head.get("tool_name"),
        "status": head.get("status"),
        "description": head.get("description") or "",
        "attributes": attrs,
    }


# ====================================================================
# 속성 수정 — DBMS_CLOUD_AI_AGENT.SET_ATTRIBUTE(object_name, object_type, attribute_name, attribute_value)
# ====================================================================

_SET_ATTR_PLSQL = (
    "BEGIN DBMS_CLOUD_AI_AGENT.SET_ATTRIBUTE("
    "object_name => :on, object_type => :ot, "
    "attribute_name => :an, attribute_value => :av); END;"
)


async def _set_attribute(database: str, object_type: str, object_name: str,
                         attribute_name: str, value: Any) -> dict:
    if value is None:
        value = ""
    if not isinstance(value, str):
        value = str(value)
    try:
        await db.execute(
            database,
            _SET_ATTR_PLSQL,
            on=object_name, ot=object_type, an=attribute_name, av=value,
        )
    except Exception as exc:
        msg = _first_line(exc)
        logger.warning("SET_ATTRIBUTE failed: db=%s type=%s name=%s attr=%s: %s",
                       database, object_type, object_name, attribute_name, msg)
        raise HTTPException(status_code=400, detail={"error": msg})
    return {"ok": True, "object_type": object_type, "object_name": object_name,
            "attribute_name": attribute_name}


@router.put("/teams/{name}/attributes/{attribute_name}")
async def set_team_attribute(name: str, attribute_name: str, payload: dict,
                              database: str = Depends(current_db)) -> dict:
    return await _set_attribute(database, "TEAM", name, attribute_name, payload.get("value", ""))


@router.put("/{name}/attributes/{attribute_name}")
async def set_agent_attribute(name: str, attribute_name: str, payload: dict,
                               database: str = Depends(current_db)) -> dict:
    return await _set_attribute(database, "AGENT", name, attribute_name, payload.get("value", ""))


@router.put("/tasks/{name}/attributes/{attribute_name}")
async def set_task_attribute(name: str, attribute_name: str, payload: dict,
                              database: str = Depends(current_db)) -> dict:
    return await _set_attribute(database, "TASK", name, attribute_name, payload.get("value", ""))


@router.put("/tools/{name}/attributes/{attribute_name}")
async def set_tool_attribute(name: str, attribute_name: str, payload: dict,
                              database: str = Depends(current_db)) -> dict:
    return await _set_attribute(database, "TOOL", name, attribute_name, payload.get("value", ""))


# ====================================================================
# AI 추천 — agent role / task·tool instruction 을 SELECT AI(chat) 로 개선 제안
#   Thinking 과정(실행 트레이스) + 현재 저장값을 컨텍스트로 삼는다.
# ====================================================================

_GENERATE_CHAT_SQL = (
    "SELECT DBMS_CLOUD_AI.GENERATE(prompt => :p, profile_name => :pn, action => 'chat') AS r "
    "FROM dual"
)
# kind → (표시 라벨, 대상 attribute_name)
_SUGGEST_KIND = {
    "agent": ("Agent", "role"),
    "task": ("Task", "instruction"),
    "tool": ("Tool", "instruction"),
}
_SUGGEST_THINKING_MAXLEN = 8000


async def _pick_profile(database: str, prefer: str | None) -> str | None:
    """추천 호출에 쓸 Profile — 지정값 우선, 없으면 ENABLED(없으면 아무거나) 첫 Profile."""
    if prefer:
        return prefer
    rows = await db.fetch_all(
        database,
        "SELECT profile_name FROM USER_CLOUD_AI_PROFILES "
        "WHERE status = 'ENABLED' ORDER BY profile_name",
    )
    if not rows:
        rows = await db.fetch_all(
            database, "SELECT profile_name FROM USER_CLOUD_AI_PROFILES ORDER BY profile_name")
    return rows[0]["profile_name"] if rows else None


@router.post("/suggest-attribute")
async def suggest_attribute(payload: dict, database: str = Depends(current_db)) -> dict:
    kind = (payload.get("kind") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    if kind not in _SUGGEST_KIND:
        raise HTTPException(status_code=400, detail={"error": "kind must be agent/task/tool"})
    if not name:
        raise HTTPException(status_code=400, detail={"error": "name required"})
    label, attribute = _SUGGEST_KIND[kind]
    current = (payload.get("current") or "").strip()
    thinking = (payload.get("thinking") or "").strip()
    if len(thinking) > _SUGGEST_THINKING_MAXLEN:
        thinking = thinking[:_SUGGEST_THINKING_MAXLEN] + "\n…(생략)"

    profile_name = await _pick_profile(
        database, (payload.get("profile_name") or "").strip() or None)
    if not profile_name:
        raise HTTPException(status_code=400, detail={"error": "사용 가능한 AI Profile 이 없습니다"})

    attr_ko = "역할(role)" if attribute == "role" else "지시문(instruction)"
    thinking_block = f"\n\n[에이전트 팀 실행 과정(Thinking)]\n{thinking}" if thinking else ""
    prompt = (
        "당신은 Oracle AI Agent Team 설정을 개선하는 전문가입니다.\n"
        f"아래는 {label} '{name}' 의 현재 {attr_ko} 입니다.\n"
        f"이 {label} 가 더 정확하고 명확하게 동작하도록 {attr_ko} 를 한국어로 개선해 제안해 주세요.\n"
        "실행 과정(Thinking)이 제공되면 그 맥락을 반영하되, 간결하고 구체적인 지시문으로 작성하세요.\n"
        "제안 텍스트만 출력하고, 따옴표나 'AI:' 같은 접두어·부가 설명은 붙이지 마세요.\n\n"
        f"[현재 {attr_ko}]\n{current or '(비어 있음)'}"
        f"{thinking_block}"
    )

    try:
        row = await db.fetch_one(database, _GENERATE_CHAT_SQL, p=prompt, pn=profile_name)
    except Exception as exc:
        msg = _first_line(exc)
        logger.warning("suggest-attribute GENERATE failed: db=%s kind=%s name=%s: %s",
                       database, kind, name, msg)
        raise HTTPException(status_code=400, detail={"error": msg})

    suggestion = ((row or {}).get("r") or "").strip()
    # LLM 이 종종 양끝에 따옴표를 붙임 — 제거
    if len(suggestion) >= 2 and suggestion[0] in "\"'" and suggestion[-1] == suggestion[0]:
        suggestion = suggestion[1:-1].strip()
    return {"kind": kind, "name": name, "attribute": attribute,
            "profile_name": profile_name, "suggestion": suggestion}


# ====================================================================
# 실행
# ====================================================================

# 프롬프트 전체를 :user_prompt 바인드로, 매번 새 conversation 으로 실행.
_RUN_PLSQL = build_run_team_block()


@router.post("/teams/run")
async def run_team(payload: dict, database: str = Depends(current_db)) -> dict:
    team_name = (payload.get("team_name") or "").strip()
    user_prompt = (payload.get("user_prompt") or "").strip()
    if not team_name:
        raise HTTPException(status_code=400, detail={"error": "team_name required"})
    if not user_prompt:
        raise HTTPException(status_code=400, detail={"error": "user_prompt required"})

    pool = db.get_pool(database)
    t0 = time.perf_counter()
    conv_id = ""
    result_str = ""
    try:
        async with pool.acquire() as conn:
            with conn.cursor() as cur:
                out_conv = cur.var(str, size=4000)
                out_answer = cur.var(oracledb.DB_TYPE_CLOB)
                await cur.execute(
                    _RUN_PLSQL,
                    {
                        "team_name": team_name,
                        "user_prompt": user_prompt,
                        "out_conv": out_conv,
                        "out_answer": out_answer,
                    },
                )
                conv_id = out_conv.getvalue() or ""
                result_str = await read_clob(out_answer.getvalue())
            await conn.commit()
    except Exception as exc:
        logger.warning("RUN_TEAM failed: db=%s team=%s: %s", database, team_name, _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc), "team": team_name})

    total_ms = int((time.perf_counter() - t0) * 1000)
    timeline_payload = await build_timeline_and_logs(database, conv_id)
    return {
        "conversation_id": conv_id,
        "total_elapsed_ms": total_ms,
        "result": result_str or "",
        "timeline": timeline_payload["timeline"],
        "thinking": timeline_payload["thinking"],
        "raw_logs": timeline_payload["raw_logs"],
    }


@router.get("/conversations/{conv_id}/timeline")
async def conversation_timeline(conv_id: str, database: str = Depends(current_db)) -> dict:
    return await build_timeline_and_logs(database, conv_id)


# ====================================================================
# 타임라인 + raw 로그 빌더
# ====================================================================

def _to_ms(td) -> int:
    """timedelta → 정수 ms."""
    if td is None:
        return 0
    return int(td.total_seconds() * 1000)


# Thinking 과정 — 각 Agent/Task 별 LLM 프롬프트(원문)를 처리 순서대로 펼친다.
# 하드코딩 conversation_id 대신 실행된 conversation_id 를 :cid 로 바인딩.
# f_agent_step_title 는 사용자 정의 함수 — 미존재 시 쿼리가 실패하므로 호출부에서
# 오류를 잡아 패널에 그대로 노출한다 (타임라인은 영향받지 않음).
_THINKING_SQL = """
WITH latest_team AS (
  SELECT team_exec_id, team_name, start_date
  FROM user_ai_agent_team_history
  WHERE conversation_id = :cid
),
latest_task AS (
    SELECT team_exec_id, task_name, agent_name, conversation_params, start_date,
           ROW_NUMBER() OVER (PARTITION BY team_exec_id, task_name, agent_name
                             ORDER BY start_date DESC) as rn
  FROM user_ai_agent_task_history
)
SELECT
  team.team_name,
  task.task_name,
  task.agent_name,
  ROW_NUMBER() OVER (ORDER BY p.created ASC NULLS LAST) AS step_no,
  f_agent_step_title(COALESCE(p.prompt, p.prompt_response)) as step_title,
  COALESCE(p.prompt, p.prompt_response) AS raw_prompt,
  p.conversation_id
FROM latest_team team
JOIN latest_task task
  ON team.team_exec_id = task.team_exec_id
 AND task.rn = 1
LEFT JOIN user_cloud_ai_conversation_prompts p
  ON p.conversation_id = JSON_VALUE(task.conversation_params, '$.conversation_id')
ORDER BY p.created ASC NULLS LAST
"""


async def _fetch_thinking(database: str, conv_id: str) -> dict:
    """Thinking SQL 실행 결과 (rows) + 오류 메시지(error)."""
    if not conv_id:
        return {"rows": [], "error": None}
    try:
        rows = await db.fetch_all(database, _THINKING_SQL, cid=conv_id)
        return {"rows": rows, "error": None}
    except Exception as exc:
        msg = _first_line(exc)
        logger.warning("thinking query failed: db=%s conv=%s: %s", database, conv_id, msg)
        return {"rows": [], "error": msg}


async def build_timeline_and_logs(database: str, conv_id: str) -> dict:
    """conversation_id 로 team_exec_id 를 찾아 task/tool 이력을 시간축에 맞춤.

    agents.run_team / conversations 타임라인 + chat.send 가 공유한다.
    """
    if not conv_id:
        return {"timeline": [], "thinking": {"rows": [], "error": None}, "raw_logs": {
            "conversation_prompts": [], "task_history": [], "tool_history": [],
        }}

    # 1. team_history: conversation_id → team_exec_id, start_date
    #    TIMESTAMP WITH TIME ZONE 은 thin mode 미지원 → CAST AS TIMESTAMP 로 (UTC) 변환
    #    Thinking 쿼리는 독립적이라 함께 병렬 실행한다.
    th, thinking = await asyncio.gather(
        db.fetch_all(
            database,
            "SELECT team_exec_id, team_name, state, "
            "       CAST(SYS_EXTRACT_UTC(start_date) AS TIMESTAMP) AS start_date, "
            "       CAST(SYS_EXTRACT_UTC(end_date)   AS TIMESTAMP) AS end_date "
            "  FROM USER_AI_AGENT_TEAM_HISTORY WHERE conversation_id = :cid "
            " ORDER BY start_date",
            cid=conv_id,
        ),
        _fetch_thinking(database, conv_id),
    )
    timeline: list[dict] = []
    task_history: list[dict] = []
    tool_history: list[dict] = []

    if th:
        team_exec_ids = [r["team_exec_id"] for r in th]
        base_start = th[0]["start_date"]
        exec_ids_payload = json.dumps(team_exec_ids)

        # 2. task_history — 동일 conversation 에 여러 team_exec 가 있을 수 있어 모두 합침
        #    task_order ASC 로 조회하고 INPUT/OUTPUT(CLOB) 도 함께 가져온다.
        tasks = await db.fetch_all(
            database,
            "SELECT th.task_order, th.agent_name, th.task_name, th.state, "
            "       th.input, th.result AS output, "
            "       CAST(SYS_EXTRACT_UTC(th.start_date) AS TIMESTAMP) AS start_date, "
            "       CAST(SYS_EXTRACT_UTC(th.end_date)   AS TIMESTAMP) AS end_date "
            "  FROM USER_AI_AGENT_TASK_HISTORY th "
            "  JOIN JSON_TABLE(:payload, '$[*]' COLUMNS (eid VARCHAR2(64) PATH '$')) j "
            "    ON th.team_exec_id = j.eid "
            " ORDER BY th.task_order, th.start_date",
            payload=exec_ids_payload,
        )
        # 3. tool_history (개별 invocation) — task_order / input / output(CLOB) 포함
        tools = await db.fetch_all(
            database,
            "SELECT toh.invocation_id, toh.task_order, toh.tool_name, toh.agent_name, toh.task_name, "
            "       toh.input, toh.output, "
            "       CAST(SYS_EXTRACT_UTC(toh.start_date) AS TIMESTAMP) AS start_date, "
            "       CAST(SYS_EXTRACT_UTC(toh.end_date)   AS TIMESTAMP) AS end_date "
            "  FROM USER_AI_AGENT_TOOL_HISTORY toh "
            "  JOIN JSON_TABLE(:payload, '$[*]' COLUMNS (eid VARCHAR2(64) PATH '$')) j "
            "    ON toh.team_exec_id = j.eid "
            " ORDER BY toh.task_order, toh.start_date",
            payload=exec_ids_payload,
        )

        # tool 노드를 (agent, task) 키로 묶어 gantt 에 사용한다.
        # raw_logs 의 tool_history 는 호출(invocation) 단위로 task_order/input/output 을 그대로 노출.
        tools_by_task: dict[tuple, list[dict]] = {}
        for r in tools:
            sd = r.get("start_date")
            ed = r.get("end_date")
            elapsed = _to_ms(ed - sd) if (ed and sd) else None
            tool_history.append({
                "task_order": r.get("task_order"),
                "tool_name": r.get("tool_name") or "",
                "input": r.get("input") or "",
                "output": r.get("output") or "",
                "elapsed_ms": elapsed,
            })
            if sd is None:
                continue
            key = (r.get("agent_name") or "?", r.get("task_name") or "?")
            tools_by_task.setdefault(key, []).append({
                "label": r.get("tool_name") or "?",
                "type": "tool",
                "level": 3,
                "start_ms": _to_ms(sd - base_start),
                "end_ms": _to_ms((ed or sd) - base_start),
            })
        for nodes in tools_by_task.values():
            nodes.sort(key=lambda x: x["start_ms"])

        # task 노드를 agent 별로 묶는다 (최초 등장 순서 = start_date 순서 유지)
        agent_order: list[str] = []
        tasks_by_agent: dict[str, list[dict]] = {}
        for r in tasks:
            sd = r.get("start_date")
            ed = r.get("end_date")
            if sd is None:
                continue
            agent = r.get("agent_name") or "?"
            task = r.get("task_name") or "?"
            node = {
                "label": task,
                "type": "task",
                "level": 2,
                "start_ms": _to_ms(sd - base_start),
                "end_ms": _to_ms((ed or sd) - base_start),
                "_tools": tools_by_task.get((agent, task), []),
            }
            if agent not in tasks_by_agent:
                tasks_by_agent[agent] = []
                agent_order.append(agent)
            tasks_by_agent[agent].append(node)
            elapsed = _to_ms((ed - sd)) if ed and sd else None
            task_history.append({
                "task_order": r.get("task_order"),
                "task_name": task,
                "status": r.get("state") or "",
                "input": r.get("input") or "",
                "output": r.get("output") or "",
                "elapsed_ms": elapsed,
            })

        # pre-order 평탄화: Team(0) → Agent(1) → Task(2) → Tool(3)
        for r in th:
            sd = r.get("start_date")
            ed = r.get("end_date")
            if sd is not None:
                timeline.append({
                    "label": r.get("team_name") or "",
                    "type": "team",
                    "level": 0,
                    "start_ms": _to_ms(sd - base_start),
                    "end_ms": _to_ms((ed or sd) - base_start),
                })
        for agent in agent_order:
            agent_tasks = tasks_by_agent[agent]
            # Agent 레벨 바 = 소속 Task 들의 시간 범위 집계
            timeline.append({
                "label": agent,
                "type": "agent",
                "level": 1,
                "start_ms": min(t["start_ms"] for t in agent_tasks),
                "end_ms": max(t["end_ms"] for t in agent_tasks),
            })
            for tnode in agent_tasks:
                tool_nodes = tnode.pop("_tools")
                timeline.append(tnode)
                timeline.extend(tool_nodes)

    # 4. conversation_prompts → role/content 펼치기 (user + assistant)
    raw_prompts = await db.fetch_all(
        database,
        "SELECT conversation_prompt_id, prompt_action, prompt, prompt_response, "
        "       CAST(SYS_EXTRACT_UTC(created) AS TIMESTAMP) AS created "
        "  FROM USER_CLOUD_AI_CONVERSATION_PROMPTS "
        " WHERE conversation_id = :cid "
        " ORDER BY created",
        cid=conv_id,
    )
    convo: list[dict] = []
    for p in raw_prompts:
        pid = p.get("conversation_prompt_id") or ""
        ts = str(p.get("created")) if p.get("created") is not None else ""
        if p.get("prompt"):
            convo.append({
                "prompt_id": pid,
                "role": "user",
                "content": p.get("prompt") or "",
                "ts": ts,
            })
        if p.get("prompt_response"):
            convo.append({
                "prompt_id": pid,
                "role": f"assistant ({p.get('prompt_action') or ''})".strip(" ()"),
                "content": p.get("prompt_response") or "",
                "ts": ts,
            })

    return {
        "timeline": timeline,
        "thinking": thinking,
        "raw_logs": {
            "conversation_prompts": convo,
            "task_history": task_history,
            "tool_history": tool_history,
        },
    }
