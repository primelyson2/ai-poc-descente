"""아주 단순한 인메모리 슬라이딩 윈도우 rate-limit (DB·외부 의존 없음).

PoC 단일 프로세스 가정. 무차별 대입(로그인)·메일 스팸(분실신고) 완화용.
멀티 워커/수평 확장 시에는 공유 저장소가 필요하지만 본 PoC 범위 밖.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

_hits: dict[str, deque[float]] = defaultdict(deque)


def check(key: str, max_calls: int, window_sec: float, now: float | None = None) -> bool:
    """허용되면 True(요청을 기록), 한도 초과면 False.

    key 별로 window_sec 동안 max_calls 회까지 허용한다.
    """
    t = time.time() if now is None else now
    dq = _hits[key]
    cutoff = t - window_sec
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= max_calls:
        return False
    dq.append(t)
    if not dq:  # 빈 deque 는 메모리 정리
        _hits.pop(key, None)
    return True
