-- db/deploy/03_ords_install.sql
-- Run on the ORDS-enabled ADB schema after ASTA_PKG compiles.
-- IMPORTANT: db/ords/asta_ords_module.sql references ASTA.ASTA_PKG explicitly.
-- Patch that file first if the package owner is not ASTA.

SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
WHENEVER SQLERROR EXIT SQL.SQLCODE

PROMPT == ASTA ORDS module install ==
SHOW USER

PROMPT Installing ORDS module asta.v1...
@db/ords/asta_ords_module.sql

PROMPT ORDS module install complete.
PROMPT Expected base path: asta/
