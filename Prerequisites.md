# 사전 준비사항 (Prerequisites)

SELECT AI / AI Agent Team 기능을 사용하려면 애플리케이션이 접속할 **DB 사용자**에게 아래 권한을 미리 부여해야 합니다. ADMIN(또는 DBA 권한 보유자)으로 접속해 1회 실행합니다.

> 아래 예시의 사용자명 `askoracle` 은 실제 접속 DB 사용자명으로 바꿔서 실행하세요.

## DB 패키지 실행 권한 부여

```sql
-- Grant Database User Access to DBMS Packages
GRANT EXECUTE on DBMS_CLOUD_AI_AGENT to askoracle;
GRANT EXECUTE on DBMS_CLOUD_AI to askoracle;
GRANT EXECUTE on DBMS_NETWORK_ACL_ADMIN to askoracle;
GRANT EXECUTE on DBMS_CLOUD to askoracle;
GRANT CREATE ANY CONTEXT TO askoracle;
GRANT DROP ANY CONTEXT TO askoracle;
GRANT EXECUTE ON DBMS_RLS TO askoracle;
GRANT SELECT ON v$mapped_sql TO askoracle;
```

## 클라우드 인증(Principal Auth) 활성화

```sql
-- ENABLE_PRINCIPAL_AUTH → "이 사용자, 이 클라우드 인증 방식 써도 됨 (기능 활성화)"
BEGIN
    DBMS_CLOUD_ADMIN.ENABLE_PRINCIPAL_AUTH(
        provider => 'OCI',
        username => 'askoracle'
    );
END;
/
```
