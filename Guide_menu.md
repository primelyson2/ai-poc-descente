# 메뉴 관리 가이드 — 고객별 좌측 메뉴 분리 (URL 프리셋)

이 도구는 여러 고객 PoC에 재사용됩니다. **URL 쿼리 파라미터 `?customer=<key>`** 로 고객마다 **보여줄 좌측 메뉴 세트(프리셋)** 와 **헤더 타이틀**을 다르게 고정할 수 있습니다. 고객에게는 `?customer=` URL만 전달하면 그 고객용 메뉴 구성만 노출됩니다.

| 접속 URL | 동작 |
|---|---|
| `http://<host>/` (파라미터 없음) | **기존 방식 그대로** — 모든 메뉴 노출 + Tool관리에서 브라우저별 노출 토글 |
| `http://<host>/?customer=company1` | `company1` 프리셋의 메뉴만 노출 + 헤더 타이틀 교체 |
| `http://<host>/?customer=<미정의 key>` | 정의되지 않은 key → **기존 방식으로 폴백**(전체 노출) |

> 관리자는 **파라미터 없는 기본 URL** 로 접속해 DB·Tool 을 설정하고, 고객에게는 `?customer=<key>` URL 을 전달합니다.

---

## 1. 프리셋 정의 파일 — `static/menu_presets.json`

고객별 프리셋을 **한 파일**에 JSON 으로 정의합니다(백엔드 불필요).

> **git 공유 안 함 — project(배포) 별 독립 관리.** 실제 파일 `static/menu_presets.json` 은 **`.gitignore` 로 추적 제외**됩니다(각 배포가 자기 고객 목록을 따로 관리). git 에는 템플릿 **`static/menu_presets.json.example`** 만 공유됩니다(`config.yaml`/`models.txt` 와 동일한 패턴).
>
> **최초 세팅:** 배포 후 템플릿을 복사해 실제 파일을 만들고 편집하세요.
> ```bash
> cd project
> cp static/menu_presets.json.example static/menu_presets.json   # 이후 이 파일을 편집
> ```
> 실제 파일이 **없어도** 앱은 정상 기동합니다 — 이 경우 프리셋 기능이 비활성(전체 메뉴, 기존 동작)일 뿐입니다.

```json
{
  "company1": {
    "title": "Company1 AI PoC",
    "menus": ["profiles", "objects", "nl2sql", "history", "vpd", "chat"]
  },
  "demo": {
    "title": "Oracle SELECT AI Demo",
    "menus": ["profiles", "agents", "nl2sql", "chat"]
  }
}
```

| 필드 | 설명 |
|---|---|
| **key** (`company1`, `demo`, …) | URL 의 `?customer=<key>` 와 매칭되는 고객 식별자 |
| `title` | 헤더 브랜드 문구·브라우저 탭 제목으로 표시(예: `Company1 AI PoC`) |
| `menus` | **보여줄 메뉴 id(=route) 화이트리스트.** 여기 없는 메뉴는 전부 숨김 |

**고객 추가** = key 하나 추가, **고객 삭제** = key 제거. 저장 후 새로고침이면 즉시 반영됩니다(서버 재시작 불필요).

> ⚠️ **중요:** 프리셋이 활성일 때는 `menus` 목록이 **유일한** 노출 기준입니다. 관리 메뉴(`databases`·`access`)도 `menus` 에 **명시하지 않으면 숨겨집니다.** 고객 화면에서 Database 관리·Tool관리까지 보이게 하려면 `menus` 에 `"databases"`, `"access"` 를 직접 넣으세요.

---

## 2. 메뉴 id (route) 목록

`menus` 에 넣는 값은 좌측 메뉴의 **id(route)** 입니다. `static/index.html` 의 `data-route` 속성, `static/js/app.js` 의 `ROUTES`/`MANAGED_MENUS` 와 동일합니다.

| 메뉴 id (route) | 좌측 메뉴 라벨 | 화면 설명 |
|---|---|---|
| `profiles` | AI Profile Test | AI Profile 조회·속성·SELECT AI 생성 테스트 |
| `agents` | AI Agent Team Test | AI Agent Team 실행·타임라인 |
| `objects` | AI Profile Object Meta | 테이블/컬럼 Comment·Annotation 메타데이터 관리 |
| `nl2sql` | Select AI Test - Table list | 질문·조회컬럼 기반 NL2SQL 테스트(질문관리·comment추천) |
| `history` | Select AI Test - History | v$mapped_sql 기반 질의·생성SQL 이력·평가 |
| `predefined` | Select AI Test - Predefined Query | 사전 정의 질의 세트 실행 |
| `persona` | Select AI Test - 페르소나분석 | 페르소나 기반 분석 |
| `vpd` | Select AI Security - VPD | VPD 정책·Application Context 보안 테스트 |
| `chat` | AI Chat | Multi-Turn AI Chat(RUN_TEAM) |
| `api` | API관리(개발중) | ORDS REST 스크립트 생성·호출 테스트(프런트 전용) |
| `databases` | Database 관리 | ADB 등록·Wallet 업로드·연결 관리 |
| `access` | Tool관리 | 접근 키·메뉴 노출·Local Storage 관리 |

> 좌측 메뉴 **표시 순서는 항상 `index.html` 의 nav 순서**입니다. `menus` 배열의 순서는 노출 여부만 결정하고 화면 순서를 바꾸지 않습니다.

---

## 2.1 메뉴별 상세 설명

각 메뉴가 하는 일과 주요 기능, 관련 DB 객체를 정리합니다. 고객 PoC 범위에 맞춰 `menus` 에 넣을 메뉴를 고를 때 참고하세요.

### `profiles` — AI Profile Test
SELECT AI 의 기본 단위인 **AI Profile** 을 테스트하는 화면입니다.
- **주요 기능**: 등록된 Profile 목록·속성(`object_list`, `model`, `provider` 등) 조회, 프롬프트 입력 후 **SELECT AI 생성**(`showsql`/`runsql`/`showprompt`/`chat` 등 action 별 실행)과 응답·생성 SQL·소요시간 비교, 여러 Profile/여러 회차 **동시 측정**, `[스크립트]` 로 실제 실행되는 `DBMS_CLOUD_AI.GENERATE` 문 확인, Profile 평가(사용자 피드백) 탭.
- **관련 DB 객체**: `USER_CLOUD_AI_PROFILES(_ATTRIBUTES)`, `DBMS_CLOUD_AI.GENERATE` / `SET_ATTRIBUTE`.
- **용도**: "이 질문을 이 Profile 로 돌리면 어떤 SQL/답이 나오나" 를 가장 직접적으로 확인하는 기본 화면.

### `agents` — AI Agent Team Test
여러 에이전트가 협업하는 **AI Agent Team** 을 실행·분석하는 화면입니다.
- **주요 기능**: Team/Agent/Task/Tool 구성 조회, `RUN_TEAM` 실행, 실행 결과와 **단계별 타임라인**(각 에이전트의 START/END, thinking, 도구 호출) 재구성.
- **관련 DB 객체**: `USER_AI_AGENT_TEAMS/_AGENTS/_TASKS/_TOOLS(+_ATTRIBUTES/_HISTORY)`, `DBMS_CLOUD_AI_AGENT.RUN_TEAM`.
- **용도**: 단일 Profile 을 넘어서 다단계 에이전트 협업 시나리오를 검증.

### `objects` — AI Profile Object Meta
SELECT AI 답변 품질을 좌우하는 **스키마 메타데이터(Comment·Annotation)** 를 관리하는 화면입니다.
- **주요 기능**: 테이블/컬럼의 **Comment 조회·수정**(`COMMENT ON`), **Annotation 추가·삭제**(`ALTER … ANNOTATIONS`, 23ai), 대소문자 보존, Profile 의 `object_list` 대상 객체 탐색.
- **관련 DB 객체**: `ALL_TAB_COMMENTS`/`ALL_COL_COMMENTS`, `USER_ANNOTATIONS_USAGE`, `COMMENT ON` / `ALTER … ANNOTATIONS`.
- **용도**: LLM 이 테이블·컬럼의 의미를 더 잘 이해하도록 메타데이터를 다듬어 생성 SQL 품질을 개선(23ai 미만이거나 `USER_ANNOTATIONS_USAGE` 가 없으면 Annotation 영역 비활성화).

### `nl2sql` — Select AI Test - Table list
질문과 **조회할 컬럼**을 지정해 NL2SQL 생성을 테스트하고, 좋은 질문·컬럼 세트를 관리하는 화면입니다.
- **주요 기능**: 질문/조회컬럼/정렬기준 입력 → SELECT AI 실행, **질문관리방식**(local storage / DB) 전환, DB 방식은 질문·컬럼을 `T_NL2SQL_QUESTION`/`T_NL2SQL_COLUMN` 에 저장·검색·선택(빌더·검색·컬럼선택 팝업), 선택 컬럼의 **관련성 AI 평가**(Tool관리 체크 시), **comment추천**(직전 생성 SQL·목표 SQL 을 비교해 Comment/Annotation 개선안을 AI 로 제안).
- **관련 DB 객체**: `DBMS_CLOUD_AI.GENERATE`, `T_NL2SQL_QUESTION`/`T_NL2SQL_COLUMN`(DB 방식, 자동 생성). 자세한 사용법은 `Guide_질문관리.md`.
- **용도**: 고객 실제 질문으로 반복 테스트하며 질문·컬럼·메타데이터를 함께 다듬는 핵심 실습 화면.

### `history` — Select AI Test - History
실행된 SELECT AI 질의와 **생성된 SQL 이력**을 조회·평가하는 화면입니다.
- **주요 기능**: `v$mapped_sql` 기반으로 질의(SQL Fulltext)와 생성 SQL(Mapped SQL) 조회, **시작/종료 일시 범위·텍스트 like** 필터, 팝업에서 전체 텍스트 **복사**, 각 이력의 생성 SQL **평가**(AI 로 적절성 판정·사유).
- **관련 DB 객체**: `v$mapped_sql`(shared pool — 세션/재시작 시 소멸 가능).
- **용도**: 어떤 질의가 어떤 SQL 로 번역됐는지 사후 검토·평가. (영구 보존이 필요하면 별도 이력 테이블 캡처 방안 검토.)

### `predefined` — Select AI Test - Predefined Query
미리 정의해 둔 **질의 세트를 실행**하는 화면입니다.
- **주요 기능**: 사전 정의된 대표 질문 묶음을 선택·실행해 결과를 빠르게 확인(데모·회귀 확인용).
- **용도**: 매번 질문을 타이핑하지 않고 정해진 시나리오를 반복 시연.

### `persona` — Select AI Test - 페르소나분석
**페르소나(사용자 유형)** 관점의 분석을 수행하는 화면입니다.
- **주요 기능**: 페르소나 정의를 바탕으로 질의·분석을 구성해 실행. 자세한 내용은 `Guide_페르소나관리.md`.
- **용도**: 사용자 유형별로 다른 질문·해석이 필요한 시나리오 시연.

### `vpd` — Select AI Security - VPD
행 수준 보안(**Virtual Private Database**)을 설정·검증하는 화면입니다.
- **주요 기능**: 공통 파라미터(`{NAME}`/`{SCHEMA}`/`{TABLE}`)로 1·2·3단계 **VPD 스크립트 생성·편집·DB 적용**, 정책/정책함수·Application Context/Package **삭제**, 설정 실행 후 **Application Context 자동 재조회**, `DBA_CONTEXT`(SCHEMA 검색) 뷰어, 정책 사용중지.
- **관련 DB 객체**: `DBMS_RLS`, Application Context(`CREATE CONTEXT`/`DBMS_SESSION`), `DBA_CONTEXT`.
- **용도**: SELECT AI 가 접근하는 테이블에 사용자별 행 필터를 걸어 **보안 통제 시나리오**를 시연. (3-tier 커넥션 풀에서의 컨텍스트 공유 주의는 `Guide_Select-AI.md` §4 참고.)

### `chat` — AI Chat
**Multi-Turn 대화형** 인터페이스로 Agent Team 을 호출하는 화면입니다.
- **주요 기능**: **Chat설정**(Team / 변수 / User Prompt)을 골라 메시지 전송 → `RUN_TEAM` 호출, Multi Turn ON 시 `conversation_id` 로 대화 컨텍스트 유지, 단계별 thinking/timeline 조회, 설정 팝업에서 **실행 스크립트 조회**(RUN_TEAM 익명블록 미리보기).
- **관련 DB 객체**: `DBMS_CLOUD_AI_AGENT.RUN_TEAM`, `DBMS_CLOUD_AI.CREATE_CONVERSATION`.
- **용도**: 대화형 데모. 여러 턴에 걸친 후속 질문·맥락 유지를 보여줄 때.

### `api` — API관리 (개발중)
ORDS REST 엔드포인트를 다루는 화면입니다(현재 **프런트 전용**).
- **주요 기능**: `ORDS.DEFINE_MODULE/TEMPLATE/HANDLER` **스크립트 생성**, [생성 내역]은 mock, [호출 테스트]만 실제 `fetch`.
- **비고**: 백엔드 라우터가 아직 없어 DB 무관 경로로 진입 가능. 정식 기능화 시 mock→실쿼리/DDL 로 교체 예정.
- **용도**: SELECT AI 결과를 REST 로 노출하는 흐름을 개념 시연.

### `databases` — Database 관리 *(관리용)*
여러 **Autonomous Database 를 등록·관리**하는 화면입니다.
- **주요 기능**: Wallet zip 업로드로 **DB 등록/수정/삭제**, 연결 상태 확인, 헤더 드롭다운에 나타날 DB 구성. 변경 시 `config.yaml` 갱신 + 해당 풀만 재기동(서버 재시작 불필요). 비밀번호/Wallet 비밀번호는 저장만 하고 화면에 노출하지 않음.
- **용도**: 도구를 처음 세팅하거나 대상 DB 를 바꿀 때 사용하는 **관리자 화면**. 고객 프리셋에서는 보통 숨깁니다(관리자만 기본 URL 로 접근).

### `access` — Tool관리 *(관리용)*
도구 자체의 접근·구성을 관리하는 화면입니다.
- **주요 기능**: 사전공유 **접근 키** 설정·회전(+SMTP 키 복구), **메뉴 노출 관리**(브라우저별 토글, 프리셋 활성 시 비활성화), **Local Storage 관리**(선택 DB 의 저장 설정·프롬프트를 JSON 으로 내보내기/가져오기).
- **용도**: 접근 통제·메뉴 구성·데이터 이식을 다루는 **관리자 화면**. 고객 프리셋에서는 보통 숨깁니다.

> **관리용 두 메뉴(`databases`·`access`)** 는 고객 프리셋에서 제외하는 것을 권장합니다. 관리자는 파라미터 없는 기본 URL 로 접속해 사용하고, 고객에게는 실습·시연 메뉴만 담은 `?customer=` URL 을 전달하세요.

---

## 3. 동작 방식 (요약)

1. 페이지 로드 시 `app.js` 가 `static/menu_presets.json` 을 fetch 합니다.
2. URL 의 `?customer=<key>` 를 읽어 프리셋을 선택합니다.
3. **프리셋 있음** → `menus` 화이트리스트에 있는 메뉴만 노출, `title` 로 헤더/탭 제목 교체. (브라우저별 Tool관리 숨김 설정은 무시)
4. **프리셋 없음/미정의 key** → 기존 동작(모든 메뉴 + Tool관리 브라우저별 토글 유지, 기본 타이틀).
5. `?customer=` 는 메뉴 이동(해시 변경) 후에도 URL 에 유지되어 프리셋이 지속됩니다.

프리셋이 활성이면 **Tool관리 → 메뉴 관리** 의 토글은 비활성화되고, 안내 문구(`URL 고객 프리셋 '<key>' 적용 중…`)가 표시됩니다.

---

## 4. 주의

- **`menu_presets.json` 은 git 으로 공유되지 않습니다** — `.gitignore` 로 추적 제외되어 **배포별로 독립 관리**합니다. git 에는 템플릿 `menu_presets.json.example` 만 공유됩니다(§1 최초 세팅 참고). 두 project(`project`·`project-descente`) 는 각자 자기 실제 파일을 가집니다.
- **비밀이 아닙니다** — 메뉴 구성일 뿐이나, 접속정보/비밀번호는 절대 넣지 마세요(비밀은 `config.yaml`·Wallet 전용).
- **접근 통제가 아니라 화면 구성용입니다.** 고객이 다른 key 를 입력하면 그 프리셋을 볼 수 있습니다. 실제 권한 통제는 DB 계정 권한·VPD 등으로 합니다.
- **DB 사전 준비**: 고객 프리셋에서 `databases`(Database 관리) 를 숨기면, 접속 가능한 DB 가 없을 때 복구 진입이 불가합니다. **관리자가 미리 DB 를 등록·연결한 뒤** 고객 URL 을 전달하세요.
- 프리셋에서 `nl2sql` 을 숨기면 그 하위 옵션(AI분석·질문-조회컬럼 관련성평가)도 함께 사라집니다.
