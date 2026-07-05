-- Extend the exact LLM call audit log for ORA-driven candidate repair calls.
DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count
  FROM user_constraints
  WHERE table_name = 'ASTA_LLM_CALL_LOG'
    AND constraint_name = 'ASTA_LLM_CALL_STAGE_CK';

  IF l_count > 0 THEN
    EXECUTE IMMEDIATE
      'ALTER TABLE asta_llm_call_log DROP CONSTRAINT asta_llm_call_stage_ck';
  END IF;

  EXECUTE IMMEDIATE q'[
    ALTER TABLE asta_llm_call_log ADD CONSTRAINT asta_llm_call_stage_ck
      CHECK (stage IN ('DIAGNOSIS', 'CANDIDATE_SQL', 'REPAIR_SQL'))
  ]';
END;
/
