# ASTA AI SQL Tuning Assistant Mindmap

아래 Mermaid mindmap은 ASTA 프로그램의 주요 구성요소와 처리 흐름을 간단히 표현한 것입니다.

```mermaid
mindmap
  root((AI SQL Tuning Assistant))
    UI
      SQL 입력
      LLM 참고사항 선택 입력
      AI 분석 실행
      현재 진행 상태
      보고서 다운로드
    FastAPI Proxy
      run_id 즉시 발급
      Background analyze 실행
      progress polling
      report 조회
      ORDS proxy only
    ADB ORDS / PL/SQL
      ASTA_PKG
        전체 orchestration
        progress 기록
        before/after 비교
      ASTA_LLM_PKG
        tuning prompt 생성
        LLM rewrite
        final review
      ASTA_REPORT_PKG
        Markdown 결과서 생성
        XPLAN 원문 append
        테이블 통계 및 인덱스 append
      ASTA_VECTOR_PKG
        유사 사례 검색
        결과서 Vector KB 저장
      ASTA_SOURCE_BRIDGE_PKG
        Source DB Link 호출
        Source evidence 수집
    Source Evidence
      DB Link 기반 수집
      원본 SQL metrics
      SQL_ID / child cursor
      DBMS_XPLAN 원문
      테이블 통계
      컬럼 통계
      인덱스 정보
    AI 분석 Flow
      요청 접수
      SQL Guard
      원본 SQL Evidence 수집
      SQL Tuning Advisor
      Vector KB 검색
      LLM 1차 튜닝
      튜닝 SQL Evidence 수집
      Before/After 비교
      Final Review
      Report 생성
      Vector 저장
    결과서
      결론
      병목 진단
      튜닝 전후 수치 비교
      튜닝 전 SQL
      튜닝 후 SQL
      튜닝 전 XPLAN 원문
      튜닝 후 XPLAN 원문
      사용자 참고사항 반영
      테이블 통계 및 인덱스 정보
      작업 수행 이력
    핵심 원칙
      Source DB 직접 접속 금지
      BaseDB는 DB Link / ORDS 경유
      LLM은 evidence 기반 판단
      XPLAN은 LLM 재작성 금지
      원문 artifact 직접 출력
      결과 동일성 검증 우선
```

## 보기 방법

VS Code에서는 Mermaid preview 확장을 설치한 뒤 Markdown preview로 보면 됩니다.

GitHub나 Mermaid 지원 문서 도구에서는 이 파일을 그대로 열면 mindmap으로 렌더링됩니다.

## 수정 팁

- 큰 덩어리는 최상위 노드로 유지합니다.
- 상세 구현 함수명은 필요한 경우에만 하위 노드로 추가합니다.
- 발표용으로는 `Source Evidence`, `AI 분석 Flow`, `결과서` 3개 가지를 중심으로 설명하면 가장 이해하기 쉽습니다.
