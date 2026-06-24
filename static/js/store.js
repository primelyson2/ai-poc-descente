/**
 * store.js — localStorage 를 현재 선택 DB 이름으로 네임스페이스(데이터 키 전용).
 *   - 데이터 화면(Profile/Chat/Agent)의 저장 키는 window.Store.get/set 로 접근한다.
 *   - 키 포맷: `base::<dbName>` (예: "aiChat.savedConfigs::MYADB").
 *   - oai.db(선택 DB 자체)·auth 토큰류 등 전역 키는 이 헬퍼 대상이 아니다.
 *   - Tool관리 내보내기/가져오기도 동일한 `base::db` 규칙을 사용한다(여기서 포맷 정의).
 */
(function () {
  function dbName() {
    return (window.DBSelector && window.DBSelector.current()) || "__none__";
  }
  function scopedKey(base) {
    return base + "::" + dbName();
  }

  window.Store = {
    // 읽기 시 1회 마이그레이션: 전역 키 값이 있고 현재 DB 스코프 값이 없으면 현재 DB 로 이동.
    get(base) {
      const scoped = scopedKey(base);
      if (localStorage.getItem(scoped) === null && localStorage.getItem(base) !== null) {
        localStorage.setItem(scoped, localStorage.getItem(base));
        localStorage.removeItem(base);
      }
      return localStorage.getItem(scoped);
    },
    set(base, val) {
      localStorage.setItem(scopedKey(base), val);
    },
    remove(base) {
      localStorage.removeItem(scopedKey(base));
    },
    scopedKey,
  };
})();
