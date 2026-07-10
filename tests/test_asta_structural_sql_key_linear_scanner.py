from pathlib import Path


LLM = Path("db/adb/asta_llm_pkg.sql").read_text(encoding="utf-8")


def structural_key_body() -> str:
    start = LLM.index("FUNCTION structural_sql_key(p_sql IN CLOB)")
    return LLM[start:LLM.index("END structural_sql_key;", start)]


def test_structural_key_uses_single_pass_comment_scanner():
    body = structural_key_body()

    assert "WHILE l_pos <= l_len LOOP" in body
    assert "l_state := 'BLOCK_COMMENT'" in body
    assert "l_state := 'LINE_COMMENT'" in body
    assert "l_state := 'STRING'" in body
    assert "l_state := 'QUOTED_IDENTIFIER'" in body
    assert "l_pos := l_pos + 1" in body


def test_structural_key_does_not_use_backtracking_comment_regex():
    body = structural_key_body()

    assert "(.|[[:space:]])*?" not in body
    assert "REGEXP_REPLACE(l_v, '/\\*" not in body
    assert body.count("REGEXP_REPLACE") == 1
    assert "REGEXP_REPLACE(l_out, '[[:space:]]+', ' ')" in body


def test_scanner_preserves_comment_markers_inside_literals_and_identifiers():
    body = structural_key_body()

    string_pos = body.index("l_state = 'STRING'")
    quoted_pos = body.index("l_state = 'QUOTED_IDENTIFIER'")
    block_pos = body.index("l_state = 'BLOCK_COMMENT'")
    line_pos = body.index("l_state = 'LINE_COMMENT'")
    assert string_pos < quoted_pos < line_pos < block_pos
    assert body.count("IF l_next = '''' THEN") == 1
    assert "IF l_next = '\"' THEN" in body
    assert "IF l_char IN (CHR(10), CHR(13))" in body


def test_structural_key_scanner_uses_multibyte_safe_character_buffers():
    body = structural_key_body()

    assert "l_chunk       VARCHAR2(4096);" in body
    assert "l_char        VARCHAR2(4);" in body
    assert "l_next        VARCHAR2(4);" in body
    assert "IF LENGTH(l_chunk) >= 1000 THEN" in body
    assert "l_char        VARCHAR2(1);" not in body
    assert "l_next        VARCHAR2(1);" not in body
