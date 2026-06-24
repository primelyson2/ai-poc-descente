"""SMTP 메일 발송 — 접근 키 분실 복구용(관리자에게 현재 키 전송).

config.yaml 의 smtp 블록을 받아 stdlib smtplib 로 발송한다(추가 의존성 없음).
blocking 호출이므로 호출 측에서 asyncio.to_thread 로 감싼다.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage


def send_key_email(smtp_cfg: dict, to_addr: str, access_key: str) -> None:
    """현재 접근 키를 관리자 이메일로 발송. 실패 시 예외를 던진다."""
    host = (smtp_cfg.get("host") or "").strip()
    if not host:
        raise RuntimeError("SMTP 가 설정되지 않았습니다 (config.yaml 의 smtp.host)")
    port = int(smtp_cfg.get("port") or 587)
    user = (smtp_cfg.get("user") or "").strip()
    password = smtp_cfg.get("password") or ""
    security = (smtp_cfg.get("security") or "starttls").strip().lower()
    from_addr = (smtp_cfg.get("from") or user or to_addr).strip()

    msg = EmailMessage()
    msg["Subject"] = "[Oracle AI Test Tool] 접근 키 안내 (분실 신고 접수)"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(
        "Oracle AI Database Test Tool 접근 키 분실 신고가 접수되었습니다.\n\n"
        f"현재 접근 키: {access_key}\n\n"
        "이 메일을 받은 관리자는 키를 분실한 사용자에게 키를 안전하게 전달하세요.\n"
        "키가 유출되었다고 판단되면 [접근 키 관리] 화면에서 키를 회전(변경)하세요.\n"
    )

    if security == "ssl":
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            if security == "starttls":
                s.starttls(context=ssl.create_default_context())
            if user:
                s.login(user, password)
            s.send_message(msg)
