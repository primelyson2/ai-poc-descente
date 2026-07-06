/**
 * tuning_assistant.js — ASTA 연동용 독립 view.
 * 작성자: 도상훈
 * 파일 용도: OADT2 화면에서 ASTA SQL 튜닝 요청, 진행률 폴링, 결과/리포트 렌더링을 담당한다.
 *
 * 기존 화면 소스와 분리하기 위해 window.Views.tuningAssistant 만 추가한다.
 * 실제 ASTA API 연결은 OADT2 same-origin /api/asta/analyze proxy를 사용한다.
 * 엔드포인트를 호출하도록 구성했다.
 */
(function () {
  window.Views = window.Views || {};

  const DEFAULT_ORDS_BASE_URL = "/api/asta";
  const DEFAULT_ENDPOINT = `${DEFAULT_ORDS_BASE_URL}/analyze`;
  const DEFAULT_SOURCE_ID = "DB0903_TESTDB";
  const DEFAULT_AI_PROFILE = "ASTA_GROK_REASONING_PROFILE";
  const ASTA_SAMPLE_SQLS = [
    {
      id: "asta-awr-01",
      sqlId: "7rcw6d3us86r7",
      label: "SESL0640.selectList",
      workload: "OLTP",
      sql: `/*  SESL0640.selectList  */

WITH STYLE
     AS (SELECT COMP_CD
               ,STYLE_CD
               ,STYLE_NM
               ,CLASS_CD
               ,GENDER_CD
               ,LINE_CD
               ,ITEM_CD
               ,YEAR_CD
               ,SEASON_CD
               ,CATEGORY_CD
               ,CONF_CSM_AMT * 0.6 AS CONF_CSM_AMT
           FROM DSNT.TGP_STYLE_M A
          WHERE A.COMP_CD = '01'
            AND A.BRAND_CD = 'M'
            AND A.NOR_CLS_CD = '1'
            AND NOT EXISTS
                    (SELECT /*+ INDEX(VWS TGP_STYDE_L_IE2) */
                           1
                       FROM DSNT.VIF_WHOLESALE_S VWS
                      WHERE VWS.COMP_CD = A.COMP_CD
                        AND VWS.COMP_CD = '01'
                        AND VWS.STYLE_CD = A.STYLE_CD) /*홀세일 STYLE 제외*/
            AND A.YEAR_CD IN ('P', 'Q', 'R')
            AND EXISTS
                    (SELECT /*+ NO_CPU_COSTING */
                           1
                       FROM DSNT.V_STYGRP_D SD
                      WHERE SD.COMP_CD = '01'
                        AND SD.BRAND_CD = A.BRAND_CD
                        AND SD.STYLE_CD = A.STYLE_CD
                        AND SD.UPCTG_CD1 = '000000269'
                        AND SD.UPCTG_CD2 = '000269001'
                        AND SD.UPCTG_CD3 >= '269001016'
                        AND SD.UPCTG_CD3 <= '269001016'))
  SELECT /* SESL0640.selectList */
        SRC.COMP_CD
        ,SRC.BRAND_CD
        ,SRC.CONF_CSM_AMT
        ,SRC.CONF_CSM_AMT * 0.6 AS DC_AMT
        ,SRC.ITEM_CD
        ,DSNT.FN_GP_ITEM_NM2( SRC.COMP_CD, SRC.BRAND_CD, SRC.ITEM_CD) AS ITEM_NM
        ,SRC.SALE_DE
        ,MAX(SRC.SALE_DE) AS SALE_DE_DD
        ,SRC.FIRS_OUT_DE
        ,SRC.FIRS_IN_DE
        ,TO_DATE( '20260615', 'YYYYMMDD') - TO_DATE( SRC.FIRS_OUT_DE, 'YYYYMMDD') + 1 AS OUT_DAY_CNT /*경과일*/
        ,SRC.ONOFF_ORD_QTY
        ,SRC.ORD_QTY
        ,SRC.FIRS_ORD_QTY
        ,SRC.OTHER_ORD_QTY
        ,SRC.TOT_RECP_QTY
        ,SRC.RECP_QTY
        ,SRC.WH_MOV_QTY
        ,SRC.SHOP_MOV_QTY
        ,SRC.ISSU_QTY
        ,SRC.ETC_ISSU_QTY
        ,SRC.TOT_SALE_QTY
        ,NVL(SRC.PROD_SALE_QTY, 0) AS PROD_SALE_QTY
        ,NVL(SRC.PROD_SALE_AMT, 0) AS PROD_SALE_AMT
        ,NVL(SRC.PROD_CSM_AMT, 0) AS PROD_CSM_AMT
        ,NVL(SUM(SRC.P_SALE_QTY), 0) AS SALE_QTY
        ,NVL(SUM(SRC.P_SALE_AMT), 0) AS SALE_AMT
        ,NVL(SUM(SRC.P_CSM_AMT), 0) AS CSM_AMT
        ,DECODE(ORD_QTY, 0, 0, ROUND( (RECP_QTY / ORD_QTY) * 100, 1)) AS RECP_RATE /*발주입고/발주 입고율*/
        ,DECODE(RECP_QTY, 0, 0, ROUND( (ISSU_QTY / RECP_QTY) * 100, 1)) AS ISSU_RATE /*출고/발주입고 출고율*/
        ,DECODE(RECP_QTY, 0, 0, ROUND( (TOT_SALE_QTY / RECP_QTY) * 100, 1)) AS R_SALE_RATE /*총판매/발주입고 판매율*/
        ,DECODE(RW_SALE_QTY, 0, 0, ROUND( (TOT_SALE_QTY / RW_SALE_QTY) * 100, 1)) AS RW_SALE_RATE /*총판매/(발주+이관)판매율*/
        ,DECODE(TOT_RECP_QTY, 0, 0, ROUND( (TOT_SALE_QTY / TOT_RECP_QTY) * 100, 1)) AS TOT_SALE_RATE /*총판매/총입고 판매율*/
        ,DECODE(TO_DATE( '20260615', 'YYYYMMDD') - TO_DATE( SRC.FIRS_OUT_DE, 'YYYYMMDD') + 1, 0, 0, ROUND( SRC.TOT_SALE_QTY / TO_NUMBER(TO_DATE( '20260615', 'YYYYMMDD') - TO_DATE( SRC.FIRS_OUT_DE, 'YYYYMMDD') + 1), 2)) AS OUT_DAY_SALE_QTY /*평균판매수량*/
        ,DECODE(ORD_QTY, 0, 0, ROUND( (TOT_SALE_QTY / ORD_QTY) * 100, 1)) AS SALE_RATE /*판매율*/
        ,DECODE(ONOFF_SALE_QTY, 0, 0, ROUND( (TOT_SALE_QTY / ONOFF_SALE_QTY) * 100, 1)) AS ON_SALE_RATE /*ON판매율*/
        ,SRC.TOT_RECP_QTY - SRC.TOT_SALE_QTY AS STOC_QTY /*재고수량*/
    FROM (SELECT XX.COMP_CD
                ,XX.BRAND_CD
                ,XX.CONF_CSM_AMT
                ,XX.CLASS_CD
                ,XX.GENDER_CD
                ,XX.LINE_CD
                ,XX.ITEM_CD
                ,XX.STYLE_CD
                ,XX.STYLE_NM
                ,XX.COLOR_CD
                ,XX.SIZE_CD
                ,XX.YEAR_CD
                ,XX.SEASON_CD
                ,XX.CATEGORY_CD
                ,SALE_DE
                ,XX.ONOFF_ORD_QTY
                ,XX.ORD_QTY
                ,XX.FIRS_ORD_QTY
                ,XX.OTHER_ORD_QTY
                ,XX.RECP_QTY
                ,XX.RECP_QTY + XX.WH_MOV_QTY AS RW_SALE_QTY
                ,XX.RECP_QTY + XX.WH_MOV_QTY + XX.SHOP_MOV_QTY AS TOT_RECP_QTY
                ,XX.ISSU_QTY
                ,XX.ETC_ISSU_QTY
                ,XX.WH_MOV_QTY
                ,XX.SHOP_MOV_QTY
                ,XX.SALE_QTY AS TOT_SALE_QTY
                ,XX.ONOFF_SALE_QTY
                ,(SELECT MIN(WH_IS_DE)
                    FROM DSNT.TSE_DIV_L Z
                   WHERE XX.COMP_CD = Z.COMP_CD
                     AND XX.STYLE_CD = Z.STYLE_CD
                     AND XX.BRAND_CD = Z.BRAND_CD
                     AND DECODE(XX.COLOR_CD, '-', Z.COLOR_CD, XX.COLOR_CD) = Z.COLOR_CD
                     AND DECODE(XX.SIZE_CD, '-', Z.SIZE_CD, XX.SIZE_CD) = Z.SIZE_CD
                     AND Z.COMP_CD = '01'
                     AND Z.SALE_STD_CD = '3'
                     AND Z.DEL_YN = 'N')
                     AS FIRS_OUT_DE
                ,(SELECT MIN(Z.FIRS_IN_DE)
                    FROM DSNT.TGP_STYDE_L Z
                   WHERE XX.COMP_CD = Z.COMP_CD
                     AND Z.COMP_CD = '01'
                     AND XX.STYLE_CD = Z.STYLE_CD
                     AND DECODE(XX.COLOR_CD, '-', Z.COLOR_CD, XX.COLOR_CD) = Z.COLOR_CD
                     AND DECODE(XX.SIZE_CD, '-', Z.SIZE_CD, XX.SIZE_CD) = Z.SIZE_CD
                     AND Z.FIRS_IN_DE IS NOT NULL
                     AND Z.USE_YN = 'Y')
                     AS FIRS_IN_DE
                ,YY.P_SALE_QTY
                ,YY.P_SALE_AMT
                ,YY.P_CSM_AMT
                ,YY.PROD_SALE_QTY
                ,YY.PROD_SALE_AMT
                ,YY.PROD_CSM_AMT
            FROM ( /* 발주 입고 출고 판매 */
                  SELECT   X.COMP_CD
                          ,X.BRAND_CD /*, SALE_DE*/
                          ,B.ITEM_CD
                          ,'-' AS CLASS_CD
                          ,'-' AS GENDER_CD
                          ,'-' AS LINE_CD
                          ,'-' AS STYLE_CD
                          ,'-' AS STYLE_NM
                          ,0 AS CONF_CSM_AMT
                          ,'-' AS COLOR_CD
                          ,'-' AS SIZE_CD
                          ,'-' AS YEAR_CD
                          ,'-' AS SEASON_CD
                          ,'-' AS CATEGORY_CD
                          ,NVL(SUM(ONOFF_ORD_QTY), 0) AS ONOFF_ORD_QTY
                          ,NVL(SUM(ORD_QTY), 0) AS ORD_QTY
                          ,NVL(SUM(FIRS_ORD_QTY), 0) AS FIRS_ORD_QTY
                          ,NVL(SUM(OTHER_ORD_QTY), 0) AS OTHER_ORD_QTY
                          ,NVL(SUM(RECP_QTY), 0) AS RECP_QTY
                          ,NVL(SUM(ISSU_QTY), 0) AS ISSU_QTY
                          ,NVL(SUM(ETC_ISSU_QTY), 0) AS ETC_ISSU_QTY
                          ,NVL(SUM(WH_MOV_QTY), 0) AS WH_MOV_QTY
                          ,NVL(SUM(SHOP_MOV_QTY), 0) AS SHOP_MOV_QTY
                          ,NVL(SUM(SALE_QTY), 0) AS SALE_QTY
                          ,NVL(SUM(ONOFF_SALE_QTY), 0) AS ONOFF_SALE_QTY
                      FROM ( /* 발주  */
                            SELECT   A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                                    ,'I' AS ITEM_GB
                                    ,NVL(SUM(A.ORD_QTY), 0) AS ONOFF_ORD_QTY
                                    ,NVL(SUM(DECODE(A.BSALE_CLS_CD,  '2', A.ORD_QTY,  '3', A.ORD_QTY,  0)), 0) AS ORD_QTY
                                    ,NVL(SUM(DECODE(A.BSALE_CLS_CD,  '2', DECODE(A.RE_ORDR, 1, A.ORD_QTY, 0),  '3', DECODE(A.RE_ORDR, 1, A.ORD_QTY, 0),  0)), 0) AS FIRS_ORD_QTY
                                    ,NVL(SUM(DECODE(A.BSALE_CLS_CD,  '2', DECODE(A.RE_ORDR, 1, 0, A.ORD_QTY),  '3', DECODE(A.RE_ORDR, 1, 0, A.ORD_QTY),  0)), 0) AS OTHER_ORD_QTY
                                    ,0 AS RECP_QTY
                                    ,0 AS ISSU_QTY
                                    ,0 AS ETC_ISSU_QTY
                                    ,0 AS WH_MOV_QTY
                                    ,0 AS SHOP_MOV_QTY
                                    ,0 AS SALE_QTY
                                    ,0 AS ONOFF_SALE_QTY
                                FROM DSNT.TSE_ORDER_S A
                               WHERE 1 = 1
                                 AND A.COMP_CD = '01'
                                 AND A.BRAND_CD = 'M'
                                 AND A.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52'
                                 /* AND    A.BSALE_CLS_CD IN ('3', '2')    영업구분 : Online */

                                 AND A.SALE_KIND_CD = '1'
                            GROUP BY A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                            UNION ALL
                              SELECT A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                                    ,'I' AS ITEM_GB
                                    ,0 AS ONOFF_ORD_QTY
                                    ,0 AS ORD_QTY
                                    ,0 AS FIRS_ORD_QTY
                                    ,0 AS OTHER_ORD_QTY
                                    ,NVL(SUM(A.RECP_QTY), 0) AS RECP_QTY
                                    ,NVL(SUM(A.ISSU_QTY), 0) AS ISSU_QTY
                                    ,0 AS ETC_ISSU_QTY
                                    /*, NVL (SUM (CASE WHEN A.ETC_YN = 'N' THEN A.ISSU_QTY END), 0) AS ISSU_QTY
                                    , NVL (SUM (CASE WHEN A.ETC_YN = 'Y' THEN A.ISSU_QTY END), 0) AS ETC_ISSU_QTY*/
                                    ,0 AS WH_MOV_QTY
                                    ,0 AS SHOP_MOV_QTY
                                    ,0 AS SALE_QTY
                                    ,0 AS ONOFF_SALE_QTY
                                FROM DSNT.TSE_INOUT_S A /*  입출고 집계  */
                               WHERE 1 = 1
                                 AND A.COMP_CD = '01'
                                 AND A.BRAND_CD = 'M'
                                 AND A.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52'
                                 AND A.SALE_STD_CD = '3'
                                 AND A.BSAL_CLS_CD IN ('3', '2') /* 영업구분 */
                                 AND A.SALE_KIND_CD = '1'
                                 AND A.ETC_YN = 'N'
                            GROUP BY A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                            UNION ALL
                              SELECT A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                                    ,'I' AS ITEM_GB
                                    ,0 AS ONOFF_ORD_QTY
                                    ,0 AS ORD_QTY
                                    ,0 AS FIRS_ORD_QTY
                                    ,0 AS OTHER_ORD_QTY
                                    ,0 AS RECP_QTY
                                    ,0 AS ISSU_QTY
                                    ,0 AS ETC_ISSU_QTY
                                    ,0 AS WH_MOV_QTY
                                    ,0 AS SHOP_MOV_QTY
                                    ,NVL(SUM(A.SALE_QTY), 0) AS SALE_QTY
                                    ,0 AS ONOFF_SALE_QTY
                                FROM DSNT.TSE_SALE_MON_S A
                               WHERE 1 = 1
                                 AND A.COMP_CD = '01'
                                 AND A.BRAND_CD = 'M'
                                 AND A.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52'
                                 AND A.SALE_STD_CD = '3'
                                 AND A.BSAL_CLS_CD IN ('3', '2') /* 영업구분 */
                                 AND A.SALE_KIND_CD = '1'
                            GROUP BY A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                            UNION ALL
                              /* 창고 이동 */
                              SELECT /*+ NO_ADAPTIVE_PLAN NO_MERGE INDEX(A TSE_ISSU_PK) */
                                    A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                                    ,'I' AS ITEM_GB
                                    ,0 AS ONOFF_ORD_QTY
                                    ,0 AS ORD_QTY
                                    ,0 AS FIRS_ORD_QTY
                                    ,0 AS OTHER_ORD_QTY
                                    ,0 AS RECP_QTY
                                    ,0 AS ISSU_QTY
                                    ,0 AS ETC_ISSU_QTY
                                    ,SUM(ISSU_QTY) * -1 AS WH_MOV_QTY
                                    ,0 AS SHOP_MOV_QTY
                                    ,0 AS SALE_QTY
                                    ,0 AS ONOFF_SALE_QTY
                                FROM DSNT.TSE_ISSU_D A
                               WHERE 1 = 1
                                 AND A.COMP_CD = '01'
                                 AND A.BRAND_CD = 'M'
                                 AND A.ISSU_TYPE_CD = '6'
                                 AND A.SHOP_CD = 'M' || '9999'
                                 AND A.WH_CD = 'A12111' /* 온라인 창고 */
                                 AND A.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52'
                                 AND (A.COMP_CD, A.BRAND_CD, A.ISSU_DE, A.SHOP_CD, A.ISSU_SLIP_NO, A.ISSU_SLIP_SN, A.ISSU_SLIP_SEQ) IN (SELECT /*+ INDEX(A TSE_ISSU_11) */
                                                                                                                                              A.COMP_CD
                                                                                                                                              ,A.BRAND_CD
                                                                                                                                              ,A.TRGT_ISSU_DE
                                                                                                                                              ,A.TRGT_SHOP_CD
                                                                                                                                              ,A.TRGT_SLIP_NO
                                                                                                                                              ,A.TRGT_SLIP_SN
                                                                                                                                              ,A.TRGT_SLIP_SEQ
                                                                                                                                          FROM DSNT.TSE_ISSU_D A
                                                                                                                                              ,STYLE B
                                                                                                                                         WHERE 1 = 1
                                                                                                                                           AND A.COMP_CD = B.COMP_CD
                                                                                                                                           AND A.STYLE_CD = B.STYLE_CD
                                                                                                                                           AND A.COMP_CD = '01'
                                                                                                                                           AND A.BRAND_CD = 'M'
                                                                                                                                           AND A.SHOP_CD = 'M' || '9999'
                                                                                                                                           AND A.ISSU_TYPE_CD = '6'
                                                                                                                                           AND A.WH_CD IN ('A11111', 'B1ZZ32') /*OFF 정상, E비즈임시*/
                                                                                                                                           AND A.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52')
                            GROUP BY A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                            UNION ALL
                              /* 매장연동 Data */
                              SELECT /*+ NO_ADAPTIVE_PLAN  INDEX( A TSE_ISSU_D_IE11) */
                                    A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                                    ,'I' AS ITEM_GB
                                    ,0 AS ONOFF_ORD_QTY
                                    ,0 AS ORD_QTY
                                    ,0 AS FIRS_ORD_QTY
                                    ,0 AS OTHER_ORD_QTY
                                    ,0 AS RECP_QTY
                                    ,0 AS ISSU_QTY
                                    ,0 AS ETC_ISSU_QTY
                                    ,0 AS WH_MOV_QTY
                                    ,SUM(ISSU_QTY) AS SHOP_MOV_QTY
                                    ,0 AS SALE_QTY
                                    ,0 AS ONOFF_SALE_QTY
                                FROM DSNT.TSE_ISSU_D A
                               WHERE 1 = 1
                                 AND A.DEL_YN = 'N'
                                 AND A.COMP_CD = '01'
                                 AND A.BRAND_CD = 'M'
                                 AND A.ISSU_TYPE_CD = '2'
                                 AND A.ISSU_CLS_CD = '24'
                                 AND A.WH_CD IN ('B1ZZ11')
                                 AND A.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52'
                                 AND A.SHOP_CD IN (SELECT /*+ UNNEST */
                                                         SHOP_CD
                                                     FROM DSNT.TSE_SHOP_M
                                                    WHERE COMP_CD = '01'
                                                      AND BRAND_CD = 'M'
                                                      AND CHL_CFG_CD = '6')
                            GROUP BY A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                            UNION ALL
                              SELECT A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD
                                    ,'I' AS ITEM_GB
                                    ,0 AS ONOFF_ORD_QTY
                                    ,0 AS ORD_QTY
                                    ,0 AS FIRS_ORD_QTY
                                    ,0 AS OTHER_ORD_QTY
                                    ,0 AS RECP_QTY
                                    ,0 AS ISSU_QTY
                                    ,0 AS ETC_ISSU_QTY
                                    ,0 AS WH_MOV_QTY
                                    ,0 AS SHOP_MOV_QTY
                                    ,0 AS SALE_QTY
                                    ,NVL(SUM(A.SALE_QTY), 0) AS ONOFF_SALE_QTY
                                FROM DSNT.TSE_SALE_MON_S A
                               WHERE 1 = 1
                                 AND A.COMP_CD = '01'
                                 AND A.BRAND_CD = 'M'
                                 AND A.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52'
                                 AND A.SALE_STD_CD = '3'
                                 AND A.SALE_KIND_CD = '1'
                            GROUP BY A.COMP_CD
                                    ,A.BRAND_CD
                                    ,A.STYLE_CD
                                    ,A.COLOR_CD
                                    ,A.SIZE_CD) X
                          ,STYLE B
                     WHERE 1 = 1
                       AND X.COMP_CD = B.COMP_CD
                       AND X.STYLE_CD = B.STYLE_CD
                  GROUP BY X.COMP_CD, X.BRAND_CD /*, SALE_DE*/
                                                , B.ITEM_CD) XX
                ,( /* 기간판매 */
                  SELECT COMP_CD
                        ,BRAND_CD
                        ,SALE_DE
                        ,CLASS_CD
                        ,GENDER_CD
                        ,LINE_CD
                        ,ITEM_CD
                        ,STYLE_CD
                        ,STYLE_NM
                        ,COLOR_CD
                        ,SIZE_CD
                        ,YEAR_CD
                        ,SEASON_CD
                        ,CATEGORY_CD
                        ,P_SALE_QTY
                        ,P_SALE_AMT
                        ,P_CSM_AMT
                        ,SUM(P_SALE_QTY) OVER (PARTITION BY COMP_CD, BRAND_CD, ITEM_CD) AS PROD_SALE_QTY
                        ,SUM(P_SALE_AMT) OVER (PARTITION BY COMP_CD, BRAND_CD, ITEM_CD) AS PROD_SALE_AMT
                        ,SUM(P_CSM_AMT) OVER (PARTITION BY COMP_CD, BRAND_CD, ITEM_CD) AS PROD_CSM_AMT
                    FROM (  SELECT A.COMP_CD
                                  ,A.BRAND_CD
                                  ,A.SALE_DE
                                  ,B.ITEM_CD
                                  ,'-' AS CLASS_CD
                                  ,'-' AS GENDER_CD
                                  ,'-' AS LINE_CD
                                  ,'-' AS STYLE_CD
                                  ,'-' AS STYLE_NM
                                  ,0 AS CONF_CSM_AMT
                                  ,'-' AS COLOR_CD
                                  ,'-' AS SIZE_CD
                                  ,'-' AS YEAR_CD
                                  ,'-' AS SEASON_CD
                                  ,'-' AS CATEGORY_CD
                                  ,NVL(SUM(A.SALE_QTY), 0) AS P_SALE_QTY
                                  ,NVL(SUM(A.REAL_SALE_AMT), 0) AS P_SALE_AMT
                                  ,NVL(SUM(A.SALE_AMT), 0) AS P_CSM_AMT
                              /*
                              , SUM(A.SALE_QTY) AS P_SALE_QTY
                              , SUM(A.SALE_AMT) AS P_SALE_AMT
                              , SUM(A.CSM_AMT)  AS P_CSM_AMT
                              */
                              FROM DSNT.TSE_SALE_DAY_S A
                                  ,STYLE B
                             WHERE 1 = 1
                               AND A.COMP_CD = B.COMP_CD
                               AND A.STYLE_CD = B.STYLE_CD
                               AND A.COMP_CD = '01'
                               AND A.BRAND_CD = 'M'
                               AND A.SALE_STD_CD = '3'
                               AND A.BSAL_CLS_CD IN ('2', '3')
                               AND A.SALE_KIND_CD = '1'
                               AND A.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52'
                               AND A.SALE_DE BETWEEN '20260604' AND '20260615'
                          GROUP BY A.COMP_CD
                                  ,A.BRAND_CD
                                  ,A.SALE_DE
                                  ,B.ITEM_CD)) YY
           WHERE 1 = 1
             AND XX.COMP_CD = YY.COMP_CD(+)
             AND XX.BRAND_CD = YY.BRAND_CD(+)
             AND XX.CLASS_CD = YY.CLASS_CD(+)
             AND XX.GENDER_CD = YY.GENDER_CD(+)
             AND XX.LINE_CD = YY.LINE_CD(+)
             AND XX.ITEM_CD = YY.ITEM_CD(+)
             AND XX.STYLE_CD = YY.STYLE_CD(+)
             AND XX.STYLE_NM = YY.STYLE_NM(+)
             AND XX.COLOR_CD = YY.COLOR_CD(+)
             AND XX.SIZE_CD = YY.SIZE_CD(+)
             AND XX.YEAR_CD = YY.YEAR_CD(+)
             AND XX.SEASON_CD = YY.SEASON_CD(+)
             AND XX.CATEGORY_CD = YY.CATEGORY_CD(+)) SRC
   WHERE 1 = 1
     AND NOT (SRC.ONOFF_ORD_QTY > 0
          AND SRC.ORD_QTY = 0
          AND SRC.TOT_RECP_QTY = 0)
GROUP BY SRC.COMP_CD
        ,SRC.BRAND_CD
        ,SRC.CONF_CSM_AMT
        ,SRC.ITEM_CD
        ,SRC.SALE_DE
        ,SRC.FIRS_OUT_DE
        ,SRC.FIRS_IN_DE
        ,SRC.ONOFF_ORD_QTY
        ,SRC.ORD_QTY
        ,SRC.FIRS_ORD_QTY
        ,SRC.OTHER_ORD_QTY
        ,SRC.RECP_QTY
        ,SRC.ISSU_QTY
        ,SRC.ETC_ISSU_QTY
        ,SRC.WH_MOV_QTY
        ,SRC.SHOP_MOV_QTY
        ,SRC.RW_SALE_QTY
        ,SRC.TOT_RECP_QTY
        ,SRC.TOT_SALE_QTY
        ,SRC.PROD_SALE_QTY
        ,SRC.PROD_SALE_AMT
        ,SRC.PROD_CSM_AMT
        ,SRC.ONOFF_SALE_QTY
ORDER BY SRC.COMP_CD, SRC.BRAND_CD, SRC.ITEM_CD`,
    },
    {
      id: "asta-awr-02",
      label: "02 · 상관 EXISTS 반복",
      pattern: "CORRELATED_EXISTS_COUNT",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=120) SELECT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.ITEM_CD FROM B WHERE EXISTS (SELECT 1 FROM DSNT.V_STYGRP_D G WHERE G.COMP_CD=B.COMP_CD AND G.BRAND_CD=B.BRAND_CD AND TRIM(G.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
    {
      id: "asta-awr-03",
      label: "03 · 상관 NOT EXISTS 반복",
      pattern: "CORRELATED_NOT_EXISTS",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.STYLE_NM FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=80) SELECT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.STYLE_NM FROM B WHERE NOT EXISTS (SELECT 1 FROM DSNT.VIF_WHOLESALE_S W WHERE W.COMP_CD=B.COMP_CD AND TRIM(W.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
    {
      id: "asta-awr-04",
      label: "04 · 제외키 상관 반복",
      pattern: "CORRELATED_EXCLUSION_KEYS",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=70) SELECT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.ITEM_CD FROM B WHERE NOT EXISTS (SELECT 1 FROM DSNT.VIF_WHOLESALE_S W WHERE W.COMP_CD=B.COMP_CD AND TRIM(W.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
    {
      id: "asta-awr-05",
      label: "05 · 중복 CTE 이중 스캔",
      pattern: "DUPLICATE_CTE_SCAN",
      workload: "OLTP",
      sql: `WITH R AS (SELECT I.COMP_CD,I.BRAND_CD,I.STYLE_CD,SUM(I.RECP_QTY) Q FROM DSNT.TSE_INOUT_S I WHERE I.COMP_CD='01' AND I.BRAND_CD='M' AND I.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' GROUP BY I.COMP_CD,I.BRAND_CD,I.STYLE_CD),X AS (SELECT I.COMP_CD,I.BRAND_CD,I.STYLE_CD,SUM(I.ISSU_QTY) Q FROM DSNT.TSE_INOUT_S I WHERE I.COMP_CD='01' AND I.BRAND_CD='M' AND I.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' GROUP BY I.COMP_CD,I.BRAND_CD,I.STYLE_CD) SELECT R.COMP_CD,R.BRAND_CD,R.STYLE_CD,CAST(R.Q AS NUMBER) RECP_QTY,CAST(X.Q AS NUMBER) ISSU_QTY FROM R JOIN X ON X.COMP_CD=R.COMP_CD AND X.BRAND_CD=R.BRAND_CD AND X.STYLE_CD=R.STYLE_CD`,
    },
    {
      id: "asta-awr-06",
      label: "06 · 함수 적용 조건",
      pattern: "FUNCTION_PREDICATE",
      workload: "OLTP",
      sql: `SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND NVL(S.COMP_CD,'-')='01' AND UPPER(NVL(S.BRAND_CD,'-'))='M' AND TRIM(S.STYLE_CD) BETWEEN 'MP111MET21' AND 'MR222LTS52' AND SUBSTR(S.STYLE_CD,1,2) IN ('MP','MQ','MR') AND ROWNUM<=200`,
    },
    {
      id: "asta-awr-07",
      label: "07 · DISTINCT와 GROUP BY 중복",
      pattern: "REDUNDANT_DISTINCT_GROUP",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=100) SELECT DISTINCT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.ITEM_CD FROM B WHERE EXISTS (SELECT 1 FROM DSNT.V_STYGRP_D G WHERE G.COMP_CD=B.COMP_CD AND G.BRAND_CD=B.BRAND_CD AND TRIM(G.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
    {
      id: "asta-awr-08",
      label: "08 · UNION 중복 제거",
      pattern: "UNION_DUPLICATE_ELIMINATION",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=75) SELECT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.ITEM_CD FROM B WHERE EXISTS (SELECT G.COMP_CD,G.BRAND_CD,TRIM(G.STYLE_CD) STYLE_CD FROM DSNT.V_STYGRP_D G WHERE G.COMP_CD=B.COMP_CD AND G.BRAND_CD=B.BRAND_CD AND TRIM(G.STYLE_CD)=TRIM(B.STYLE_CD) UNION SELECT G.COMP_CD,G.BRAND_CD,TRIM(G.STYLE_CD) FROM DSNT.V_STYGRP_D G WHERE 1=0)`,
    },
    {
      id: "asta-awr-09",
      label: "09 · 복합키 EXISTS 재조회",
      pattern: "COMPOSITE_EXISTS_RESCAN",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=90) SELECT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.ITEM_CD FROM B WHERE EXISTS (SELECT 1 FROM DSNT.V_STYGRP_D G WHERE G.COMP_CD=B.COMP_CD AND G.BRAND_CD=B.BRAND_CD AND TRIM(G.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
    {
      id: "asta-awr-10",
      label: "10 · 이중 EXISTS 연쇄",
      pattern: "DUAL_EXISTS_CHAIN",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=60) SELECT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.ITEM_CD FROM B WHERE EXISTS (SELECT 1 FROM DSNT.V_STYGRP_D G WHERE G.COMP_CD=B.COMP_CD AND G.BRAND_CD=B.BRAND_CD AND TRIM(G.STYLE_CD)=TRIM(B.STYLE_CD)) AND EXISTS (SELECT 1 FROM DSNT.VIF_WHOLESALE_S W WHERE W.COMP_CD=B.COMP_CD AND TRIM(W.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
    {
      id: "asta-awr-11",
      label: "11 · SEMI/ANTI 혼합 반복",
      pattern: "SEMI_ANTI_MIXED",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=55) SELECT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.ITEM_CD FROM B WHERE EXISTS (SELECT 1 FROM DSNT.V_STYGRP_D G WHERE G.COMP_CD=B.COMP_CD AND G.BRAND_CD=B.BRAND_CD AND TRIM(G.STYLE_CD)=TRIM(B.STYLE_CD)) AND NOT EXISTS (SELECT 1 FROM DSNT.VIF_WHOLESALE_S W WHERE W.COMP_CD=B.COMP_CD AND TRIM(W.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
    {
      id: "asta-awr-12",
      label: "12 · 인라인 집계 중복",
      pattern: "DUPLICATE_INLINE_AGGREGATE",
      workload: "OLTP",
      sql: `SELECT A.COMP_CD,A.BRAND_CD,A.STYLE_CD,CAST(A.QTY AS NUMBER) QTY,CAST(B.FIRST_QTY AS NUMBER) FIRST_QTY FROM (SELECT O.COMP_CD,O.BRAND_CD,O.STYLE_CD,SUM(O.ORD_QTY) QTY FROM DSNT.TSE_ORDER_S O WHERE O.COMP_CD='01' AND O.BRAND_CD='M' AND O.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' GROUP BY O.COMP_CD,O.BRAND_CD,O.STYLE_CD) A JOIN (SELECT O.COMP_CD,O.BRAND_CD,O.STYLE_CD,SUM(DECODE(O.RE_ORDR,1,O.ORD_QTY,0)) FIRST_QTY FROM DSNT.TSE_ORDER_S O WHERE O.COMP_CD='01' AND O.BRAND_CD='M' AND O.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' GROUP BY O.COMP_CD,O.BRAND_CD,O.STYLE_CD) B ON B.COMP_CD=A.COMP_CD AND B.BRAND_CD=A.BRAND_CD AND B.STYLE_CD=A.STYLE_CD`,
    },
    {
      id: "asta-awr-13",
      label: "13 · EXISTS와 NOT EXISTS 연쇄",
      pattern: "EXISTS_NOT_EXISTS_CHAIN",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=60) SELECT B.* FROM B WHERE EXISTS (SELECT 1 FROM DSNT.V_STYGRP_D G WHERE G.COMP_CD=B.COMP_CD AND G.BRAND_CD=B.BRAND_CD AND TRIM(G.STYLE_CD)=TRIM(B.STYLE_CD)) AND NOT EXISTS (SELECT 1 FROM DSNT.VIF_WHOLESALE_S W WHERE W.COMP_CD=B.COMP_CD AND TRIM(W.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
    {
      id: "asta-awr-14",
      label: "14 · 월판매 GROUP BY 반복",
      pattern: "REPEATED_GROUP_BY_CTE",
      workload: "OLTP",
      sql: `WITH Q AS (SELECT M.COMP_CD,M.BRAND_CD,M.STYLE_CD,SUM(M.SALE_QTY) QTY FROM DSNT.TSE_SALE_MON_S M WHERE M.COMP_CD='01' AND M.BRAND_CD='M' AND M.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' GROUP BY M.COMP_CD,M.BRAND_CD,M.STYLE_CD),R AS (SELECT M.COMP_CD,M.BRAND_CD,M.STYLE_CD,COUNT(*) CNT FROM DSNT.TSE_SALE_MON_S M WHERE M.COMP_CD='01' AND M.BRAND_CD='M' AND M.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' GROUP BY M.COMP_CD,M.BRAND_CD,M.STYLE_CD) SELECT Q.COMP_CD,Q.BRAND_CD,Q.STYLE_CD,CAST(Q.QTY AS NUMBER) QTY,CAST(R.CNT AS NUMBER) CNT FROM Q JOIN R ON R.COMP_CD=Q.COMP_CD AND R.BRAND_CD=Q.BRAND_CD AND R.STYLE_CD=Q.STYLE_CD`,
    },
    {
      id: "asta-awr-15",
      label: "15 · 중복 함수 조건",
      pattern: "REDUNDANT_FUNCTION_FILTER",
      workload: "OLTP",
      sql: `WITH B AS (SELECT S.COMP_CD,S.BRAND_CD,S.STYLE_CD,S.ITEM_CD FROM DSNT.TGP_STYLE_M S WHERE S.COMP_CD='01' AND S.BRAND_CD='M' AND S.STYLE_CD BETWEEN 'MP111MET21' AND 'MR222LTS52' AND ROWNUM<=65) SELECT B.COMP_CD,B.BRAND_CD,B.STYLE_CD,B.ITEM_CD FROM B WHERE EXISTS (SELECT 1 FROM DSNT.V_STYGRP_D G WHERE NVL(G.COMP_CD,'-')=NVL(B.COMP_CD,'-') AND UPPER(NVL(G.BRAND_CD,'-'))=UPPER(NVL(B.BRAND_CD,'-')) AND TRIM(G.STYLE_CD)=TRIM(B.STYLE_CD))`,
    },
  ];
  const DEFAULT_STEPS = [
    { seq: 1, code: "REQUEST_RECEIVED", label: "요청 수신", status: "PENDING" },
    { seq: 2, code: "ORDS_DISPATCH", label: "분석 서버 연결", status: "PENDING" },
    { seq: 3, code: "SQL_GUARD", label: "입력 SQL 확인", status: "PENDING" },
    { seq: 4, code: "BEFORE_EVIDENCE", label: "원본 SQL 실행 정보 수집", status: "PENDING" },
    { seq: 5, code: "SQL_TUNING_ADVISOR", label: "Oracle 튜닝 권고 (기본 사용 안 함)", status: "PENDING" },
    { seq: 6, code: "LLM_REWRITE", label: "개선 SQL 만들기", status: "PENDING" },
    { seq: 7, code: "AFTER_EVIDENCE", label: "개선 SQL 안전성·성능 확인", status: "PENDING" },
    { seq: 8, code: "BEFORE_AFTER_COMPARE", label: "원본과 개선 결과 비교", status: "PENDING" },
    { seq: 9, code: "VECTOR_KB", label: "비슷한 튜닝 사례 찾기", status: "PENDING" },
    { seq: 10, code: "FINAL_REPORT", label: "결과서 만들기", status: "PENDING" },
    { seq: 11, code: "VECTOR_SAVE", label: "검증 결과 저장", status: "PENDING" },
  ];

  const FRIENDLY_ASTA_ISSUES = Object.freeze({
    CANDIDATE_RUNTIME_LIMIT: {
      title: "후보 SQL 검증 시간이 초과되었습니다",
      message: "개선 SQL의 전체 결과를 확인하는 작업이 제한 시간 안에 끝나지 않았습니다. 원본 SQL은 변경되지 않았습니다.",
      action: "같은 테스트를 바로 반복하지 말고 Run ID를 담당자에게 전달해 주세요. 결과 데이터가 큰 SQL은 검증 시간이 더 필요할 수 있습니다.",
    },
    SQL_REQUIRED: { title: "SQL을 입력해 주세요", message: "분석할 SQL이 비어 있습니다.", action: "SELECT 또는 WITH로 시작하는 조회 SQL을 입력한 뒤 다시 실행해 주세요." },
    SQL_GUARD_REJECTED: { title: "실행할 수 없는 SQL입니다", message: "ASTA는 데이터 조회용 SELECT 또는 WITH 한 문장만 실행할 수 있습니다.", action: "세미콜론으로 연결된 여러 문장, INSERT·UPDATE·DELETE·DDL, FOR UPDATE를 제거해 주세요." },
    SQL_SYNTAX_ERROR: { title: "SQL 문법을 확인해 주세요", message: "Oracle이 SQL 문장을 해석하지 못했습니다.", action: "괄호, 쉼표, 별칭, JOIN 조건을 확인한 뒤 다시 실행해 주세요." },
    SQL_INVALID_IDENTIFIER: { title: "컬럼이나 객체 이름을 찾을 수 없습니다", message: "SQL에 현재 스키마에서 확인할 수 없는 컬럼 또는 객체 이름이 있습니다.", action: "테이블 별칭과 컬럼명을 확인해 주세요." },
    SQL_AMBIGUOUS_COLUMN: { title: "어느 테이블의 컬럼인지 알 수 없습니다", message: "같은 이름의 컬럼이 여러 테이블에 있어 Oracle이 대상을 결정하지 못했습니다.", action: "컬럼 앞에 테이블 별칭을 붙여 주세요." },
    SOURCE_OBJECT_NOT_FOUND: { title: "테이블 또는 뷰를 찾을 수 없습니다", message: "분석 대상 DB에서 SQL이 참조하는 객체를 찾지 못했습니다.", action: "객체명과 스키마명을 확인하고, 계속되면 Run ID를 담당자에게 전달해 주세요." },
    SOURCE_PRIVILEGE_DENIED: { title: "조회 권한이 부족합니다", message: "ASTA 실행 계정에 필요한 객체 조회 권한이 없습니다.", action: "Run ID와 객체명을 DB 담당자에게 전달해 권한을 확인해 주세요." },
    SOURCE_DBLINK_UNAVAILABLE: { title: "분석 대상 DB에 연결할 수 없습니다", message: "ASTA 서버와 분석 대상 DB 사이의 연결이 현재 사용 가능하지 않습니다.", action: "잠시 후 다시 시도하고, 계속되면 Run ID를 운영 담당자에게 전달해 주세요." },
    CANDIDATE_FAILED: { title: "개선 SQL을 실행하지 못했습니다", message: "자동으로 만든 개선 SQL이 Oracle에서 정상 실행되지 않았습니다. 원본 SQL은 변경되지 않았습니다.", action: "튜닝 후 탭의 오류와 Run ID를 확인해 주세요." },
    CANDIDATE_ORACLE_ERROR: { title: "개선 SQL을 실행하지 못했습니다", message: "자동으로 만든 개선 SQL에서 Oracle 오류가 발생했습니다. 원본 SQL은 변경되지 않았습니다.", action: "튜닝 후 탭의 오류와 Run ID를 확인해 주세요." },
    NO_REWRITE: { title: "안전한 개선 SQL을 만들지 못했습니다", message: "현재 정보만으로는 실행 가능한 개선안을 만들 수 없었습니다.", action: "업무상 유지해야 할 조건이나 의심 구간을 참고사항에 추가해 다시 시도해 주세요." },
    FULL_RESULT_EVIDENCE_REQUIRED: { title: "전체 결과 비교가 필요합니다", message: "일부 결과만 확인되어 원본과 개선 SQL이 완전히 같은 결과인지 확정할 수 없습니다.", action: "원본 SQL은 그대로 사용하고, Run ID를 담당자에게 전달해 전체 결과 검증 상태를 확인해 주세요." },
    RESULT_EVIDENCE_INCOMPLETE: { title: "결과 비교가 끝나지 않았습니다", message: "원본과 개선 SQL의 전체 결과 확인이 완료되지 않았습니다.", action: "원본 SQL은 그대로 사용하고 잠시 후 다시 시도해 주세요." },
    RESULT_DIGEST_REQUIRED: { title: "결과 비교 정보를 만들지 못했습니다", message: "원본과 개선 SQL의 결과가 같은지 확인할 정보가 부족합니다.", action: "원본 SQL을 유지하고 Run ID를 담당자에게 전달해 주세요." },
    RESULT_DIGEST_MISMATCH: { title: "원본과 개선 SQL의 결과가 다릅니다", message: "두 SQL이 반환한 데이터가 일치하지 않아 개선 SQL을 적용하지 않았습니다.", action: "개선 SQL을 사용하지 말고 튜닝 후 탭에서 변경 조건을 확인해 주세요." },
    RESULT_METADATA_MISMATCH: { title: "결과 컬럼 구성이 다릅니다", message: "컬럼명, 순서 또는 데이터 형식이 달라 개선 SQL을 적용하지 않았습니다.", action: "개선 SQL을 사용하지 말고 SELECT 컬럼 구성을 확인해 주세요." },
    BIND_COVERAGE_INSUFFICIENT: { title: "입력값별 안전성을 충분히 확인하지 못했습니다", message: "조건값에 따라 실행 방식이 달라질 수 있어 개선 SQL을 확정하지 않았습니다.", action: "대표적인 조건값으로 다시 검증하거나 Run ID를 담당자에게 전달해 주세요." },
    MEASUREMENT_EVIDENCE_INCOMPLETE: { title: "성능 측정 횟수가 부족합니다", message: "일시적인 변동을 제외할 만큼 반복 측정이 완료되지 않았습니다.", action: "원본 SQL을 유지하고 잠시 후 다시 실행해 주세요." },
    MEASUREMENT_NOISE_TOO_HIGH: { title: "실행시간 변동이 너무 큽니다", message: "측정할 때마다 실행시간 차이가 커서 개선 여부를 확정할 수 없습니다.", action: "DB 부하가 낮을 때 다시 실행해 주세요." },
    OPTIMIZER_INTENT_EVIDENCE_INCOMPLETE: { title: "병목이 실제로 줄었는지 확인하지 못했습니다", message: "개선 SQL의 실행계획에서 목표한 반복 작업 감소를 확인할 정보가 부족합니다.", action: "원본 SQL을 유지하고 Run ID를 담당자에게 전달해 주세요." },
    OLTP_LATENCY_TARGET_NOT_MET: { title: "응답시간 기준을 통과하지 못했습니다", message: "개선 SQL의 응답시간이 온라인 업무 기준보다 길어 적용하지 않았습니다.", action: "원본 SQL을 계속 사용해 주세요." },
    BATCH_ELAPSED_TIME_NOT_IMPROVED: { title: "전체 실행시간이 줄지 않았습니다", message: "개선 SQL이 원본보다 빠르지 않아 적용하지 않았습니다.", action: "원본 SQL을 계속 사용해 주세요." },
    RUN_NOT_FOUND: { title: "분석 기록을 찾을 수 없습니다", message: "요청한 Run ID의 분석 기록이 없거나 보관기간이 지났습니다.", action: "Run ID를 다시 확인해 주세요." },
    REPORT_NOT_FOUND: { title: "결과서를 찾을 수 없습니다", message: "분석 기록은 있지만 결과서가 아직 생성되지 않았거나 보관기간이 지났습니다.", action: "잠시 후 다시 조회하고, 계속되면 Run ID를 담당자에게 전달해 주세요." },
    RESOURCE_BUSY: { title: "DB가 현재 바쁩니다", message: "필요한 DB 자원을 다른 작업이 사용 중이어서 분석을 완료하지 못했습니다.", action: "잠시 후 다시 시도해 주세요." },
    SPACE_EXHAUSTED: { title: "DB 작업 공간이 부족합니다", message: "결과 비교 중 필요한 임시 공간이 부족했습니다.", action: "반복 실행하지 말고 Run ID를 DB 담당자에게 전달해 주세요." },
    EXECUTION_CANCELLED: { title: "SQL 실행이 중단되었습니다", message: "실행 제한시간 또는 DB 요청으로 분석 SQL이 중단되었습니다. 원본 SQL은 변경되지 않았습니다.", action: "잠시 후 다시 시도하고, 계속되면 Run ID를 담당자에게 전달해 주세요." },
  });

  /**
   * 사용자/서버 문자열을 HTML로 렌더링하기 전에 이스케이프한다.
   */
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  /**
   * Oracle SQL을 sql-formatter의 PL/SQL dialect로 정리한다.
   * 라이브러리를 불러오지 못하거나 지원하지 않는 구문이면 원문을 보존한다.
   */
  function formatSql(sql) {
    const source = String(sql || "").trim();
    if (!source || typeof window.sqlFormatter?.format !== "function") return source;

    try {
      return window.sqlFormatter.format(source, {
        language: "plsql",
        keywordCase: "upper",
        tabWidth: 2,
        useTabs: false,
        linesBetweenQueries: 1,
        logicalOperatorNewline: "before",
        expressionWidth: 80,
      });
    } catch (error) {
      console.warn("ASTA SQL formatting failed; preserving the original SQL.", error);
      return source;
    }
  }

  /**
   * SQL 도구에서 복사할 때 붙는 맨 끝 세미콜론 하나만 제거한다.
   * 본문 안의 세미콜론은 서버 Guard가 계속 차단한다.
   */
  function stripTrailingSqlTerminator(sql) {
    const text = String(sql || "").trim();
    return text.endsWith(";") ? text.slice(0, -1).trimEnd() : text;
  }

  /**
   * 밀리초 실행 시간을 사람이 읽기 쉬운 문자열로 변환한다.
   */
  function formatDuration(ms) {
    if (ms == null || Number.isNaN(Number(ms))) return "-";
    const total = Math.max(0, Math.round(Number(ms)));
    const sec = total / 1000;
    if (sec < 60) return `${sec.toFixed(1)}초`;
    const min = Math.floor(sec / 60);
    return `${min}분 ${(sec % 60).toFixed(1)}초`;
  }

  /**
   * ISO 시간 문자열을 밀리초 timestamp로 파싱한다.
   */
  function parseTimeMs(value) {
    if (!value) return null;
    const ms = new Date(value).getTime();
    return Number.isFinite(ms) ? ms : null;
  }

  /**
   * 진행 단계 목록에서 전체 경과 시간을 계산한다.
   */
  function totalElapsedMs(progress, steps, isComplete) {
    const explicit = progress?.totalDurationMs ?? progress?.total_duration_ms ?? progress?.elapsed_ms ?? progress?.elapsedMs;
    if (explicit != null && !Number.isNaN(Number(explicit))) return Number(explicit);
    const sec = progress?.elapsed_total_sec ?? progress?.elapsed_total_seconds ?? progress?.total_elapsed_sec ?? progress?.duration_sec;
    if (sec != null && !Number.isNaN(Number(sec))) return Number(sec) * 1000;
    const stepTimes = steps.map((item) => parseTimeMs(item.at)).filter((ms) => ms != null);
    const start = parseTimeMs(progress?.created_at || progress?.started_at || progress?.start_time)
      ?? Math.min(...stepTimes);
    if (!Number.isFinite(start)) return null;
    const end = parseTimeMs(progress?.completed_at || progress?.ended_at || progress?.end_time)
      ?? (isComplete ? Math.max(...stepTimes) : Date.now());
    if (!Number.isFinite(end)) return null;
    return Math.max(0, end - start);
  }

  /**
   * 리포트/원문 다운로드용 텍스트 파일을 브라우저에서 생성한다.
   */
  function downloadText(filename, text) {
    const blob = new Blob([text || ""], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  /**
   * 라벨 없이 전달받은 원문만 클립보드에 복사한다.
   */
  async function copyPlainText(text) {
    const value = String(text || "");
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("clipboard copy failed");
  }

  /**
   * UI 진행률에 표시할 한 단계의 상태와 시간 정보를 만든다.
   */
  function stepWithTiming(step, status, detail, at = new Date(), elapsedMs = null) {
    const iso = at ? (at instanceof Date ? at : new Date(at)).toISOString() : "";
    return { ...step, status, detail: detail || step.detail || status, at: iso, elapsed_ms: elapsedMs };
  }

  /** 민감한 SQL literal/bind 값은 숨기되 ORA 코드와 gate reason은 보존한다. */
  function redactAstaSensitiveText(value) {
    let text = String(value ?? "");
    const hasOracleError = /ORA-/i.test(text);
    text = text.replace(/'(?:''|[^'])*'/g, "'[SQL_LITERAL_REDACTED]'");
    text = text.replace(/(:[A-Za-z][A-Za-z0-9_$#]*)\s*=\s*[^,\s)]+/g, "$1=[BIND_VALUE_REDACTED]");
    text = text.replace(/\b(SELECT|WITH|INSERT|UPDATE|DELETE|MERGE)\b[\s\S]*$/i, "[SQL_TEXT_REDACTED]");
    if (hasOracleError && !/ORA-/i.test(text)) text = `ORA-ERROR · ${text}`;
    return text.slice(0, 2000);
  }

  function astaIssueCandidates(data, fallbackMessage) {
    const value = data || {};
    const progress = value.progress && !Array.isArray(value.progress) ? value.progress : {};
    const payload = value.payload || {};
    const detail = payload.detail || {};
    return [
      value.error_code, value.error?.code, value.workflow_state?.reason_code,
      value.comparison?.verdict_reason, value.comparison?.verdict,
      progress.error_code, progress.error?.code, progress.workflow_state?.reason_code,
      payload.error_code, payload.error?.code, detail.error,
      value.message, value.error_message, value.error?.message,
      progress.error_message, progress.error?.message,
      detail.message, fallbackMessage,
    ].filter((item) => item != null && String(item).trim());
  }

  /** 내부 오류 코드는 유지하되 개발자가 이해할 제목·설명·다음 행동으로 변환한다. */
  function friendlyAstaIssue(data, fallbackMessage) {
    const value = data || {};
    const nestedProgress = value.progress && !Array.isArray(value.progress) ? value.progress : {};
    const payload = value.payload || {};
    const detail = payload.detail || {};
    const candidates = astaIssueCandidates(data, fallbackMessage);
    const combined = candidates.map((item) => String(item)).join("\n");
    let code = candidates.map((item) => String(item).trim().toUpperCase())
      .find((item) => Object.prototype.hasOwnProperty.call(FRIENDLY_ASTA_ISSUES, item));
    if (!code) {
      code = Object.keys(FRIENDLY_ASTA_ISSUES).find((key) => combined.toUpperCase().includes(key));
    }
    if (!code && /CANDIDATE EXECUTION EXCEEDED THE ADAPTIVE RUNTIME LIMIT/i.test(combined)) code = "CANDIDATE_RUNTIME_LIMIT";
    if (!code && /ORA-0090[057]|ORA-00911|ORA-0093[36]/i.test(combined)) code = "SQL_SYNTAX_ERROR";
    if (!code && /ORA-00904/i.test(combined)) code = "SQL_INVALID_IDENTIFIER";
    if (!code && /ORA-00918/i.test(combined)) code = "SQL_AMBIGUOUS_COLUMN";
    if (!code && /ORA-00942/i.test(combined)) code = "SOURCE_OBJECT_NOT_FOUND";
    if (!code && /ORA-01031/i.test(combined)) code = "SOURCE_PRIVILEGE_DENIED";
    if (!code && /ORA-01013|ORA-00028/i.test(combined)) code = "EXECUTION_CANCELLED";
    const known = code ? FRIENDLY_ASTA_ISSUES[code] : null;
    const rawTechnicalMessage = value.error_message || value.error?.message
      || nestedProgress.error_message || nestedProgress.error?.message
      || detail.message || value.message || fallbackMessage
      || "상세 원인이 제공되지 않았습니다.";
    const technicalMessage = redactAstaSensitiveText(rawTechnicalMessage);
    return known
      ? { code, ...known, technicalMessage }
      : {
          code: String(value?.error_code || value?.error?.code || value?.workflow_state?.reason_code || "ASTA_ANALYSIS_INCOMPLETE"),
          title: "분석을 완료하지 못했습니다",
          message: "안전을 위해 개선 SQL을 적용하지 않았으며 원본 SQL은 변경되지 않았습니다.",
          action: "잠시 후 다시 시도하고, 같은 문제가 계속되면 Run ID와 문의 코드를 담당자에게 전달해 주세요.",
          technicalMessage,
        };
  }

  /** 서버 상태머신과 deterministic comparison을 하나의 terminal outcome으로 해석한다. */
  function astaWorkflowOutcome(data) {
    const workflowStatus = String(data?.workflow_state?.overall_status || data?.state_machine?.overall_status || "").toUpperCase();
    const responseStatus = String(data?.status || "").toUpperCase();
    const verdict = String(data?.comparison?.verdict || data?.verdict || "").toUpperCase();
    const failures = ["BLOCKED", "REJECTED", "FAILED", "ERROR"];
    if (failures.includes(workflowStatus)) return workflowStatus;
    if (failures.includes(responseStatus)) return responseStatus;
    if (["NON_EQUIVALENT", "INSUFFICIENT_EVIDENCE", "NOT_IMPROVED", "CANDIDATE_FAILED"].includes(verdict)) return "REJECTED";
    if (workflowStatus === "ACCEPTED" || verdict === "IMPROVED") return "ACCEPTED";
    if (["COMPLETED", "DONE", "BASELINE_CAPTURED"].includes(responseStatus)) return "ACCEPTED";
    return responseStatus || workflowStatus || "RUNNING";
  }

  /** SQL/literal은 보존하되 credential, token, connection string만 UI에서 마스킹한다. */
  function redactAstaReportForUi(report) {
    return String(report || "")
      .replace(/\b(authorization\s*:\s*bearer)\s+[^\s]+/gi, "$1 [CREDENTIAL_REDACTED]")
      .replace(/\b(password|passwd|pwd|api[_-]?key|access[_-]?token|secret)\b(\s*[:=]\s*)(?:'[^']*'|"[^"]*"|[^\s,;]+)/gi, "$1$2[CREDENTIAL_REDACTED]")
      .replace(/\b(?:jdbc:oracle:thin:|oracle:\/\/)[^\s)]+/gi, "[CONNECTION_STRING_REDACTED]");
  }

  /**
   * ASTA analyze 결과와 다운로드 링크를 결과 영역에 렌더링한다.
   */
  function renderResult(target, data) {
    const report = data?.detailed_report_markdown || data?.report_markdown || data?.llm_final_report?.report_markdown || data?.report || data?.message || "구조화된 Gate 결과만 제공되었습니다.";
    const safeReport = redactAstaReportForUi(report);
    const runId = data?.run_id ? `<div class="muted">Run ID: ${escapeHtml(data.run_id)}</div>` : "";
    const errorCandidates = [
      data?.error_message,
      data?.error?.message,
      data?.comparison?.verdict_reason,
      data?.artifacts?.llm?.candidate_error,
      data?.artifacts?.llm?.generation?.candidate_error,
      data?.runtime_evidence?.error?.message,
      data?.after_evidence?.error?.message,
    ].filter((value) => typeof value === "string" && value.trim());
    const oraMessage = errorCandidates.find((value) => /ORA-\d{5}/i.test(value));
    const oraBanner = oraMessage
      ? `<div class="tuning-ora-banner"><strong>Oracle SQL 오류</strong><code>${escapeHtml(redactAstaSensitiveText(oraMessage))}</code></div>`
      : "";
    window.__astaLastReport = {
      runId: data?.run_id || "report",
      report: safeReport,
      displayReport: safeReport,
      rawReport: String(report),
    };
    target.innerHTML = `
      <div class="card tuning-report-card">
        <div class="tuning-report-header">
          <div class="tuning-report-head">
            <div class="tuning-report-title-group">
              <div class="section-title">ASTA 분석 결과</div>
              ${runId}
            </div>
            <div class="tuning-report-actions" aria-label="결과서 작업 및 스크롤 이동">
              <button class="tuning-secondary" id="asta-report-top" type="button">맨 위</button>
              <button class="tuning-secondary" id="asta-report-bottom" type="button">맨 아래</button>
            </div>
          </div>
          <div class="tuning-report-status-slot"></div>
          <div id="asta-report-tabs-host" class="tuning-report-tabs-host"></div>
        </div>
        ${oraBanner}
        <div id="asta-report-scroll" class="code-block tuning-report-scroll" tabindex="0"></div>
      </div>`;
    const reportScroller = document.getElementById("asta-report-scroll");
    renderTrustedVectorBlocks(reportScroller, window.__astaLastReport.report);
    const tabsHost = document.getElementById("asta-report-tabs-host");
    const tabList = reportScroller?.querySelector(".tuning-report-tablist");
    if (tabsHost && tabList) tabsHost.appendChild(tabList);
    const progressTarget = document.getElementById("asta-current-progress");
    const statusSlot = target.querySelector(".tuning-report-status-slot");
    if (statusSlot && progressTarget) statusSlot.appendChild(progressTarget);
    const reportActions = target.querySelector(".tuning-report-actions");
    const downloadButton = document.getElementById("asta-download-report");
    const resetButton = document.getElementById("asta-reset");
    if (downloadButton) downloadButton.hidden = false;
    if (resetButton) resetButton.hidden = false;
    if (reportActions && downloadButton && resetButton) reportActions.append(downloadButton, resetButton);
    document.getElementById("asta-report-top")?.addEventListener("click", () => reportScroller?.scrollTo({ top: 0, behavior: "smooth" }));
    document.getElementById("asta-report-bottom")?.addEventListener("click", () => reportScroller?.scrollTo({ top: reportScroller.scrollHeight, behavior: "smooth" }));
    requestAnimationFrame(() => {
      target.scrollIntoView({ block: "start", behavior: "smooth" });
      reportScroller?.focus({ preventScroll: true });
    });
  }

  // Decode character references from backend-safe code only. The result is
  // assigned through textContent, so decoded angle brackets cannot execute.
  function decodeVectorEntities(value) {
    const decoder = document.createElement("textarea");
    decoder.innerHTML = value;
    return decoder.value;
  }

  function renderTrustedVectorBlocks(container, report) {
    if (window.AstaReportTabs?.renderReportTabs) {
      window.AstaReportTabs.renderReportTabs(container, report);
      return;
    }
    const detailPattern = /<details><summary>축약 SQL 보기<\/summary>\s*<pre><code>([\s\S]*?)<\/code><\/pre>\s*<\/details>\s*(?:\[전체 결과서 보기\]\(([^)]+)\))?/g;
    const safeReportPath = /^\/api\/asta\/runs\/[A-Za-z0-9][A-Za-z0-9_.:-]*\/report(?:\/view)?$/;
    let cursor = 0;
    let match;
    const appendText = (plainText) => {
      if (!plainText) return;
      const text = document.createElement("pre");
      text.className = "tuning-report-text";
      text.textContent = plainText;
      container.appendChild(text);
    };
    while ((match = detailPattern.exec(report)) !== null) {
      appendText(report.slice(cursor, match.index));
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "축약 SQL 보기";
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = decodeVectorEntities(match[1]);
      pre.appendChild(code);
      details.append(summary, pre);
      container.appendChild(details);
      if (match[2] && safeReportPath.test(match[2])) {
        const link = document.createElement("a");
        link.href = match[2].endsWith("/view") ? match[2] : `${match[2]}/view`;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "전체 결과서 보기";
        container.appendChild(link);
      }
      cursor = detailPattern.lastIndex;
    }
    appendText(report.slice(cursor));
  }

  /**
   * API 오류 객체에서 사용자에게 보여줄 메시지를 추출한다.
   */
  function errorDetailText(err) {
    const payload = err?.payload;
    const detail = payload?.detail;
    const issue = friendlyAstaIssue(err?.progress || payload || err, err?.message);
    const queriedRunId = err?.queriedRunId || payload?.run_id || payload?.queried_run_id || "";
    const lines = [
      `문의 코드: ${issue.code}`,
      `안내: ${issue.message}`,
      `다음 행동: ${issue.action}`,
      `기술 메시지: ${issue.technicalMessage}`,
      err?.status ? `HTTP 상태: ${err.status}` : "",
      err?.url ? `조회 endpoint: ${err.url}` : "",
      queriedRunId ? `조회 run_id: ${queriedRunId}` : "",
      payload?.error_code ? `ASTA 오류 코드: ${payload.error_code}` : "",
      detail?.error ? `서버 오류: ${redactAstaSensitiveText(detail.error)}` : "",
      detail?.message ? `Oracle/상세: ${redactAstaSensitiveText(detail.message)}` : "",
    ].filter(Boolean);
    return lines.join("\n\n");
  }

  /**
   * ASTA 실행 오류를 화면의 오류 영역에 표시한다.
   */
  function renderError(target, err) {
    const issue = friendlyAstaIssue(err?.progress || err?.payload || err, err?.message);
    const detail = errorDetailText(err);
    window.__astaLastError = detail;
    target.innerHTML = `
      <div class="card stack" style="gap: var(--space-3); border-color:#fecaca; background:#fff7f7;">
        <div class="section-title" style="color:#b91c1c;">${escapeHtml(issue.title)}</div>
        <div style="color:#7f1d1d; line-height:1.55;">${escapeHtml(issue.message)}</div>
        <div style="color:#7f1d1d; line-height:1.55;"><strong>다음 행동:</strong> ${escapeHtml(issue.action)}</div>
        <div class="muted">문의 코드: <code>${escapeHtml(issue.code)}</code></div>
        <div class="tuning-actions">
          <button class="tuning-secondary" id="asta-copy-error" type="button">문의 정보 복사</button>
        </div>
        <div class="section-title">기술 정보 (문의 시 전달)</div>
        <pre class="code-block" style="white-space: pre-wrap; max-height: 420px; overflow:auto; border-color:#fecaca;">${escapeHtml(detail)}</pre>
      </div>`;
    const copyButton = document.getElementById("asta-copy-error");
    const resetButton = document.getElementById("asta-reset");
    if (resetButton) resetButton.hidden = false;
    if (copyButton) {
      copyButton.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(window.__astaLastError || detail);
          window.Toast?.show?.("담당자에게 전달할 문의 정보를 복사했습니다.", "success");
        } catch (_) {
          window.Toast?.show?.("복사하지 못했습니다. 화면의 기술 정보를 직접 선택해 주세요.", "error");
        }
      });
    }
  }

  /**
   * 진행 단계 코드를 UI 단계 순서 인덱스로 변환한다.
   */
  function progressStageIndex(step) {
    const seq = Number(step?.seq);
    if (Number.isInteger(seq) && seq >= 1 && seq <= DEFAULT_STEPS.length) return seq - 1;

    const code = String(step?.code || "").toUpperCase();
    const codeMap = {
      REQUEST_RECEIVED: 0,
      ORDS_DISPATCH: 1,
      SQL_GUARD: 2,
      BEFORE_EVIDENCE: 3,
      SQL_TUNING_ADVISOR: 4,
      LLM_REWRITE: 5,
      AFTER_EVIDENCE: 6,
      BEFORE_AFTER_COMPARE: 7,
      LLM_FINAL_REVIEW: 7,
      VECTOR_KB: 8,
      FINAL_REPORT: 9,
      VECTOR_SAVE: 10,
    };
    if (Object.prototype.hasOwnProperty.call(codeMap, code)) return codeMap[code];

    const raw = `${step.stage || ""} ${step.code || ""} ${step.label || ""} ${step.message || ""}`.toLowerCase();
    if (raw.includes("accepted") || raw.includes("request") || raw.includes("queued") || raw.includes("요청")) return 0;
    if (raw.includes("ords") || raw.includes("dispatch") || raw.includes("proxy") || raw.includes("호출")) return 1;
    if (raw.includes("guard") || raw.includes("safe") || raw.includes("안전")) return 2;
    if (raw.includes("sqltune") || raw.includes("advisor") || raw.includes("dbms_sqltune")) return 4;
    if (raw.includes("vector_save") || raw.includes("save_case") || raw.includes("auto_vector_save") || (raw.includes("vector") && (raw.includes("save") || raw.includes("저장")))) return 10;
    if (raw.includes("final_report") || raw.includes("report") || raw.includes("최종 보고서") || raw.includes("추천") || raw.includes("결과")) return 9;
    if (raw.includes("final_review") || raw.includes("second") || raw.includes("2차") || raw.includes("before/after")) return 8;
    if (raw.includes("candidate") || raw.includes("after") || raw.includes("equiv") || raw.includes("변경") || raw.includes("재수행") || raw.includes("비교")) return 7;
    if (raw.includes("genai_first") || raw.includes("first_pass") || raw.includes("rewrite") || raw.includes("1차") || raw.includes("후보")) return 6;
    if (raw.includes("vector") || raw.includes("similar") || raw.includes("유사")) return 5;
    if (raw.includes("baseline") || raw.includes("before") || raw.includes("원본") || raw.includes("xplan") || raw.includes("metrics")) return 3;
    return null;
  }

  /**
   * 서버 progress/steps 응답을 UI 렌더링에 맞는 단계 배열로 정규화한다.
   */
  function normalizeSteps(progress) {
    const incoming = Array.isArray(progress?.progress) ? progress.progress : Array.isArray(progress?.steps) ? progress.steps : [];
    if (!incoming.length) return DEFAULT_STEPS;
    const byIndex = DEFAULT_STEPS.map((step) => ({ ...step, status: "PENDING", detail: "대기", at: "", elapsed_ms: null }));
    incoming.forEach((rawStep, rawIndex) => {
      const mappedIndex = progressStageIndex(rawStep);
      const index = mappedIndex == null ? Math.min(rawIndex, DEFAULT_STEPS.length - 1) : mappedIndex;
      const base = DEFAULT_STEPS[index];
      byIndex[index] = {
        ...base,
        status: rawStep.status || byIndex[index].status || "PENDING",
        detail: rawStep.detail || rawStep.message || rawStep.label || byIndex[index].detail || "",
        at: rawStep.at || rawStep.started_at || rawStep.created_at || rawStep.updated_at || rawStep.completed_at || byIndex[index].at || "",
        elapsed_ms: rawStep.elapsed_ms ?? rawStep.duration_ms ?? rawStep.elapsedMs ?? byIndex[index].elapsed_ms ?? null,
      };
    });
    const progressedBeyondOrds = byIndex.slice(2).some((step) => {
      const status = String(step.status || "PENDING").toUpperCase();
      return status && status !== "PENDING";
    });
    if (progressedBeyondOrds && String(byIndex[1].status || "PENDING").toUpperCase() === "PENDING") {
      byIndex[1] = { ...byIndex[1], status: "DONE", detail: "ADB ORDS 분석 호출 완료" };
    }
    if (String(byIndex[7].status || "PENDING").toUpperCase() !== "PENDING" && String(byIndex[6].status || "PENDING").toUpperCase() === "PENDING") {
      byIndex[6] = { ...byIndex[6], status: "DONE", detail: "AI 1차 튜닝 완료" };
    }
    if (String(byIndex[10].status || "PENDING").toUpperCase() !== "PENDING" && String(byIndex[8].status || "PENDING").toUpperCase() === "PENDING") {
      byIndex[8] = { ...byIndex[8], status: "DONE", detail: "AI Before/After 정리 완료" };
    }
    const overall = String(progress?.status || "").toUpperCase();
    const doneStatuses = ["DONE", "COMPLETED", "SUCCESS", "ACCEPTED", "BASELINE_CAPTURED", "DBLINK_DEFERRED", "SKIPPED"];
    const failStatuses = ["FAILED", "ERROR", "BLOCKED", "REJECTED", "WARN", "WARNING"];
    if (!overall || ["READY", "IDLE", "PENDING"].includes(overall)) {
      return byIndex;
    }
    if (["COMPLETED", "DONE", "BASELINE_CAPTURED"].includes(overall)) {
      return byIndex.map((step) => {
        const status = String(step.status || "PENDING").toUpperCase();
        if (failStatuses.includes(status)) return step;
        if (doneStatuses.includes(status)) return { ...step, status: "DONE", detail: step.detail && step.detail !== "대기" ? step.detail : "완료" };
        return step;
      });
    }
    if (["FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(overall)) {
      // A terminal failure must not promote the next unexecuted PENDING step
      // to RUNNING. Preserve the authoritative failed stage from ADB.
      return byIndex;
    }
    let firstPendingSeen = false;
    return byIndex.map((step) => {
      const status = String(step.status || "PENDING").toUpperCase();
      if (doneStatuses.includes(status)) return { ...step, status: "DONE" };
      if (failStatuses.includes(status)) return step;
      if (!firstPendingSeen) { firstPendingSeen = true; return { ...step, status: "RUNNING", detail: step.detail && step.detail !== "대기" ? step.detail : "현재 실행 중" }; }
      return step;
    });
  }

  /**
   * ASTA 진행률 스택과 상태 배지를 화면에 그린다.
   */
  function renderProgressStack(target, progress) {
    const steps = normalizeSteps(progress);
    const runId = String(progress?.run_id || progress?.runId || "").trim();
    const statusText = progress?.status || "READY";
    const overall = String(statusText || "READY").toUpperCase();
    const running = steps.find((step) => String(step.status || "").toUpperCase() === "RUNNING");
    const failed = steps.find((step) => ["FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(String(step.status || "").toUpperCase()));
    const completedSteps = steps.filter((step) => ["DONE", "COMPLETED"].includes(String(step.status || "").toUpperCase()));
    const isOverallComplete = ["COMPLETED", "DONE", "BASELINE_CAPTURED"].includes(overall);
    const isOverallFailed = ["FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(overall);
    const current = isOverallComplete ? null : (isOverallFailed ? (failed || running) : (running || failed)) || completedSteps[completedSteps.length - 1] || steps[0];
    const currentStatus = isOverallComplete ? "COMPLETED" : String(current?.status || overall || "PENDING").toUpperCase();
    const isRunning = currentStatus === "RUNNING";
    const isFailed = !isOverallComplete && (["FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(currentStatus) || isOverallFailed || progress?.stale_warning || progress?.observation_level === "STALE_OR_FAILED");
    const isComplete = isOverallComplete;
    const ready = ["READY", "IDLE", "PENDING"].includes(overall) && !running && !failed && completedSteps.length === 0;
    const elapsed = !isOverallComplete && current?.elapsed_ms != null ? ` · ${formatDuration(current.elapsed_ms)}` : "";
    const beforeEvidenceRunning = String(current?.code || "").toUpperCase() === "BEFORE_EVIDENCE" && isRunning;
    let observationDetail = "";
    if (beforeEvidenceRunning) {
      observationDetail = "Source SQL 실행 요청 처리 중";
    }
    const totalElapsed = totalElapsedMs(progress, steps, isComplete);
    const totalElapsedText = !ready && totalElapsed != null ? `전체 ${formatDuration(totalElapsed)}` : "";
    const progressIssue = isFailed ? friendlyAstaIssue(progress, current?.detail || statusText) : null;
    const label = ready ? "대기 중" : isComplete ? "완료" : isFailed ? "확인 필요" : current?.label || statusText;
    const detail = isComplete ? "AI 분석이 종료되었습니다" : ready ? "SQL 입력 후 AI 분석 실행을 누르세요" : isFailed ? progressIssue.message : observationDetail || current?.detail || statusText;
    const dotClass = isFailed ? "failed" : isComplete ? "done" : isRunning ? "running" : "pending";
    target.innerHTML = `
      <div class="tuning-current-progress tuning-current-${escapeHtml(dotClass)}" title="현재 진행 단계와 전체 수행 시간을 표시합니다">
        <span class="tuning-current-label">현재 진행</span>
        <span class="tuning-current-dot" aria-hidden="true">${isRunning ? '<span class="tuning-spinner"></span>' : isComplete ? '✓' : isFailed ? '!' : ''}</span>
        <span class="tuning-current-main">${escapeHtml(label)}</span>
        <span class="tuning-current-detail">${escapeHtml([detail, elapsed].filter(Boolean).join(""))}</span>
        ${totalElapsedText ? `<span class="tuning-current-total">${escapeHtml(totalElapsedText)}</span>` : ""}
        ${runId ? `<span class="tuning-current-run-label">Run ID</span><code class="tuning-current-run-id" title="ASTA Run ID">${escapeHtml(runId)}</code><button class="tuning-copy-run-id" type="button" title="Run ID 값만 복사">복사</button>` : ""}
      </div>`;
    target.querySelector(".tuning-copy-run-id")?.addEventListener("click", async () => {
      try {
        await copyPlainText(runId);
        window.Toast?.show?.("Run ID만 복사했습니다.", "success");
      } catch (_) {
        window.Toast?.show?.("Run ID 복사에 실패했습니다.", "error");
      }
    });
  }

  /**
   * 현재 입력값에서 analyze 호출 URL을 만든다.
   */
  function buildAnalyzeUrl(input) {
    let trimmed = String(input || "").trim().replace(/\/+$/, "");
    if (/\/api\/asta(?:\/analyze)*$/i.test(trimmed)) {
      trimmed = DEFAULT_ORDS_BASE_URL;
    }
    trimmed = trimmed.replace(/\/ords\/asta\/api(?:\/analyze)*$/i, "/ords/admin/api");
    trimmed = trimmed.replace(/(?:\/analyze)+$/i, "");
    return `${trimmed}/analyze`;
  }

  /**
   * analyze URL에서 run 조회용 base URL을 계산한다.
   */
  function buildBaseUrl(input) {
    return buildAnalyzeUrl(input).replace(/\/analyze$/i, "");
  }

  /**
   * JSON API를 호출하고 HTTP/파싱 오류를 표준 오류로 변환한다.
   */
  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const text = await response.text();
    let data;
    try { data = JSON.parse(text); } catch (_) { data = { report: text }; }
    if (!response.ok) {
      const detail = data?.detail;
      const message = detail?.message || detail?.error || data?.message || data?.error || `HTTP ${response.status}`;
      const err = new Error(`${message} @ ${url}`);
      err.status = response.status;
      err.payload = data;
      throw err;
    }
    const bodyStatus = String(data?.status || "").toUpperCase();
    const errorCode = String(data?.error_code || data?.error?.code || "").toUpperCase();
    if (bodyStatus === "NOT_FOUND" || errorCode === "RUN_NOT_FOUND" || errorCode === "REPORT_NOT_FOUND") {
      const message = data?.message || data?.error?.message || errorCode || bodyStatus;
      const err = new Error(`${message} @ ${url}`);
      err.status = response.status;
      err.url = url;
      err.payload = data;
      const match = url.match(/\/runs\/([^/?#]+)/);
      if (match) err.queriedRunId = decodeURIComponent(match[1]);
      throw err;
    }
    return data;
  }

  /**
   * run_id 기준 ASTA 최종 리포트를 별도 조회한다.
   */
  async function fetchReport(baseUrl, runId) {
    const encodedRunId = encodeURIComponent(runId);
    const data = await fetchJson(`${baseUrl}/runs/${encodedRunId}/report`);
    return typeof data === "string" ? { report_markdown: data } : data;
  }

  /**
   * 서버 진행률이 없을 때 클라이언트 임시 progress 모델을 만든다.
   */
  function buildClientProgress(status, startedAt, stepIndex, stepStartedAt = startedAt, endedAt = null, detail = "") {
    const now = endedAt || new Date();
    const steps = DEFAULT_STEPS.map((step, index) => {
      if (index < stepIndex) return stepWithTiming(step, "DONE", "완료", now, null);
      if (index === stepIndex && status === "RUNNING") return stepWithTiming(step, "RUNNING", detail || "현재 실행 중", stepStartedAt, now - stepStartedAt);
      if (status === "COMPLETED") return stepWithTiming(step, "DONE", "완료", endedAt || now, null);
      if (status === "FAILED" && index === stepIndex) return stepWithTiming(step, "FAILED", detail || "실패", endedAt || now, now - stepStartedAt);
      return stepWithTiming(step, "PENDING", "대기", null, null);
    });
    return { status, startedAt, endedAt, totalDurationMs: now - startedAt, progress: steps };
  }

  /**
   * 비동기 ASTA run 진행률을 주기적으로 조회해 화면을 갱신한다.
   */
  async function pollRunProgress(baseUrl, runId, progressTarget, resultTarget) {
    const encodedRunId = encodeURIComponent(runId);
    const maxAttempts = 2400; // 40분: SQLTUNE/LLM final review 장시간 실행 허용
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const progress = await fetchJson(`${baseUrl}/runs/${encodedRunId}/progress`);
      const uiStartedAt = window.__astaRunStartedAt;
      const totalDurationMs = uiStartedAt instanceof Date ? Date.now() - uiStartedAt.getTime() : undefined;
      renderProgressStack(progressTarget, { ...progress, totalDurationMs });
      const status = String(progress?.status || "").toUpperCase();
      if (["COMPLETED", "DONE", "FAILED", "BLOCKED", "REJECTED"].includes(status)) {
        if (["FAILED", "BLOCKED", "REJECTED"].includes(status)) {
          const failedStep = (progress?.progress || progress?.steps || []).find((step) => ["FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(String(step?.status || "").toUpperCase()));
          const message = progress?.error_message || progress?.error?.message || failedStep?.detail || "ASTA 분석이 실패했습니다.";
          const issue = friendlyAstaIssue(progress, message);
          const err = new Error(issue.message);
          err.progress = progress;
          err.friendlyIssue = issue;
          throw err;
        }
        renderResult(resultTarget, await fetchReport(baseUrl, runId));
        return progress;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    try {
      const report = await fetchReport(baseUrl, runId);
      renderResult(resultTarget, report);
      renderProgressStack(progressTarget, { status: "COMPLETED", progress: DEFAULT_STEPS.map((step) => stepWithTiming(step, "DONE", "완료", new Date(), null)) });
      return { status: "COMPLETED", progress: DEFAULT_STEPS };
    } catch (err) {
      throw new Error(`진행 상태 확인 시간이 초과되었습니다. Run ID ${runId}는 계속 실행 중일 수 있습니다. 잠시 후 보고서 조회를 다시 시도하세요.`);
    }
  }

  /**
   * ASTA 튜닝 Assistant view 전체 DOM, 이벤트, API 흐름을 초기화한다.
   */
  window.Views.tuningAssistant = async function tuningAssistant() {
    const main = document.getElementById("main");
    main.innerHTML = `
      <style>
        .tuning-shell {
          --tuning-bg: #f7f8fb;
          --tuning-panel: #ffffff;
          --tuning-surface: #f3f6fb;
          --tuning-border: #dfe5ef;
          --tuning-text: #172033;
          --tuning-muted: #64748b;
          --tuning-accent: #2563eb;
          min-height: calc(100vh - 86px);
          margin: calc(var(--space-5) * -1);
          padding: clamp(18px, 2.4vw, 34px);
          color: var(--tuning-text);
          background:
            radial-gradient(circle at 12% 0%, rgba(37,99,235,0.13), transparent 30%),
            radial-gradient(circle at 88% 8%, rgba(14,165,233,0.12), transparent 28%),
            linear-gradient(135deg, #f7f8fb 0%, #ffffff 48%, #eef4ff 100%);
        }
        .tuning-hero {
          display:flex; align-items:flex-end; justify-content:space-between; gap:18px;
          margin-bottom:18px;
        }
        .tuning-kicker {
          display:inline-flex; align-items:center; gap:8px; margin-bottom:10px;
          color:#475569; font-size:12px; letter-spacing:.08em; text-transform:uppercase;
        }
        .tuning-dot { width:8px; height:8px; border-radius:999px; background:var(--tuning-accent); box-shadow:0 0 24px var(--tuning-accent); }
        .tuning-title { margin:0; font-size:clamp(30px, 4vw, 48px); line-height:1; letter-spacing:-1.05px; font-weight:590; }
        .tuning-secret-trigger { appearance:none; border:0; padding:0; margin:0; color:inherit; background:transparent; font:inherit; letter-spacing:inherit; line-height:inherit; cursor:default; }
        .tuning-secret-trigger:focus-visible { outline:2px solid #2563eb; outline-offset:3px; border-radius:3px; }
        .tuning-subtitle { margin:12px 0 0; color:var(--tuning-muted); max-width:780px; line-height:1.6; }
        .tuning-grid { display:block; }
        .tuning-card {
          border:1px solid var(--tuning-border); border-radius:22px; padding:18px;
          background:#ffffff;
          box-shadow:0 20px 55px rgba(15,23,42,.10), inset 0 1px 0 rgba(255,255,255,.9);
          backdrop-filter: blur(12px);
        }
        .tuning-card-title { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px; font-weight:590; }
        .tuning-advisor-state { display:inline-flex; align-items:center; padding:5px 10px; border:1px solid var(--tuning-border); border-radius:999px; background:var(--surface-alt, #f8fafc); color:var(--tuning-muted); font-size:12px; font-weight:650; white-space:nowrap; }
        .tuning-hero-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
        .tuning-top-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
        .tuning-current-progress { display:inline-flex; align-items:center; gap:8px; min-height:40px; max-width:min(980px, 100%); padding:8px 12px; border:1px solid #dbe3ef; border-radius:999px; background:#ffffff; color:#334155; box-shadow:0 8px 22px rgba(15,23,42,.07); }
        .tuning-current-label { color:#64748b; font-size:12px; font-weight:650; white-space:nowrap; }
        .tuning-current-run-label { color:#64748b; font-size:11px; white-space:nowrap; }
        .tuning-current-run-id { max-width:360px; overflow:hidden; text-overflow:ellipsis; color:#475569; font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; font-size:11px; white-space:nowrap; user-select:all; }
        .tuning-copy-run-id { padding:3px 7px; border:1px solid #cbd5e1; border-radius:7px; background:#f8fafc; color:#334155; font-size:11px; font-weight:650; cursor:pointer; white-space:nowrap; }
        .tuning-copy-run-id:hover { border-color:#94a3b8; background:#f1f5f9; }
        .tuning-ora-banner { display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid #fecaca; border-radius:10px; background:#fff7f7; color:#991b1b; }
        .tuning-ora-banner code { color:#7f1d1d; font-size:12px; white-space:pre-wrap; overflow-wrap:anywhere; }
        .tuning-current-dot { width:22px; height:22px; display:inline-grid; place-items:center; border-radius:999px; background:#eff6ff; color:#1d4ed8; font-size:12px; font-weight:700; flex:0 0 auto; }
        .tuning-current-running .tuning-current-dot { background:#eff6ff; }
        .tuning-current-done .tuning-current-dot { background:#dcfce7; color:#15803d; }
        .tuning-current-failed .tuning-current-dot { background:#fee2e2; color:#b91c1c; }
        .tuning-current-main { font-size:13px; font-weight:650; color:#172033; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:210px; }
        .tuning-current-detail { font-size:12px; color:#64748b; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:260px; }
        .tuning-current-total { margin-left:2px; padding:3px 8px; border-radius:999px; background:#eff6ff; color:#1d4ed8; font-size:12px; font-weight:700; white-space:nowrap; }
        .tuning-pill { color:#475569; border:1px solid #dbe3ef; border-radius:999px; padding:5px 10px; font-size:12px; background:#f8fafc; }
        .tuning-field { display:flex; flex-direction:column; gap:8px; margin-bottom:14px; }
        .tuning-field span { color:#475569; font-size:13px; font-weight:510; }
        .tuning-controls-row { display:grid; grid-template-columns:minmax(220px, .9fr) minmax(260px, 1fr) minmax(320px, 1.35fr); gap:12px; min-width:0; margin-bottom:14px; }
        .tuning-controls-row .tuning-field { min-width:0; margin-bottom:0; }
        .tuning-controls-row .tuning-input { min-width:0; }
        .tuning-sql-wrap { position:relative; display:grid; grid-template-columns:52px minmax(0,1fr); border:1px solid #dbe3ef; border-radius:14px; overflow:hidden; background:#fbfdff; box-shadow:inset 0 0 0 1px rgba(255,255,255,.75), 0 1px 2px rgba(15,23,42,.04); }
        .tuning-line-numbers { padding:18px 10px; color:#94a3b8; background:#f1f5f9; border-right:1px solid #dbe3ef; text-align:right; user-select:none; white-space:pre; overflow:hidden; font-family:'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace; font-size:14px; line-height:1.62; }
        .tuning-input, .tuning-sql {
          width:100%; box-sizing:border-box; color:#0f172a; background:#fbfdff;
          border:1px solid #dbe3ef; border-radius:14px; outline:none;
          box-shadow:inset 0 0 0 1px rgba(255,255,255,.75), 0 1px 2px rgba(15,23,42,.04);
        }
        .tuning-sql-wrap .tuning-sql { border:0; border-radius:0; box-shadow:none; }
        .tuning-input { padding:12px 14px; }
        .tuning-sql {
          height: clamp(520px, calc(100vh - 360px), 820px);
          min-height: 460px;
          resize: vertical;
          padding:18px;
          font-family:'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
          font-size:14px; line-height:1.62; tab-size:2;
          display:block;
          overflow:auto;
          overflow-y:auto;
          overflow-x:auto;
          white-space:pre;
          -webkit-overflow-scrolling:touch;
        }
        .tuning-actions { display:flex; gap:10px; flex-wrap:wrap; }
        .tuning-primary {
          border:0; border-radius:12px; padding:12px 16px; color:white; cursor:pointer;
          background:linear-gradient(135deg, #1d4ed8, #3b82f6); font-weight:590;
          box-shadow:0 12px 28px rgba(37,99,235,.24);
        }
        .tuning-secondary { border:1px solid #dbe3ef; border-radius:12px; padding:12px 14px; color:#334155; background:#ffffff; cursor:pointer; }
        .tuning-secondary:hover { transform:translateY(-1px); box-shadow:0 10px 24px rgba(15,23,42,.08); }
        .tuning-aside { position:static; margin-top:18px; }
        .tuning-step { display:flex; gap:12px; padding:13px 0; border-top:1px solid #edf2f7; color:#64748b; line-height:1.5; }
        .tuning-step:first-of-type { border-top:0; }
        .tuning-step b { color:#172033; }
        .tuning-step-running { background:linear-gradient(90deg, rgba(37,99,235,.08), transparent); margin-inline:-8px; padding-inline:8px; border-radius:12px; }
        .tuning-step-done .tuning-num, .tuning-step-completed .tuning-num { background:#dcfce7; color:#15803d; }
        .tuning-step-failed .tuning-num, .tuning-step-error .tuning-num { background:#fee2e2; color:#b91c1c; }
        .tuning-run-meta { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:8px 0 14px; padding:12px; border:1px solid #e2e8f0; border-radius:14px; background:#f8fafc; }
        .tuning-run-meta div { display:flex; flex-direction:column; gap:3px; min-width:0; }
        .tuning-run-meta b { font-size:11px; color:#64748b; font-weight:600; }
        .tuning-run-meta span { font-size:12px; color:#172033; display:inline-flex; align-items:center; gap:6px; }
        .tuning-spinner { width:14px; height:14px; border:2px solid #bfdbfe; border-top-color:#2563eb; border-radius:50%; display:inline-block; animation:tuning-spin .8s linear infinite; }
        @keyframes tuning-spin { to { transform:rotate(360deg); } }
        .tuning-num { flex:0 0 26px; height:26px; display:grid; place-items:center; border-radius:9px; background:#eff6ff; color:#1d4ed8; font-size:12px; }
        .tuning-result { margin-top:18px; }
        .tuning-report-card { min-height:min(82vh, 980px); padding:0 !important; overflow:hidden; border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface); box-shadow:none; }
        .tuning-report-header { background:var(--surface); border-bottom:1px solid var(--border); }
        .tuning-report-head { display:flex; align-items:flex-start; justify-content:space-between; gap:var(--space-3); flex-wrap:wrap; padding:var(--space-4) var(--space-4) var(--space-2); }
        .tuning-report-title-group { display:flex; flex-direction:column; gap:var(--space-1); min-width:0; color:var(--text); }
        .tuning-report-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
        .tuning-report-header .tuning-secondary { min-height:34px; padding:7px 10px; border:1px solid var(--border); border-radius:var(--radius); background:var(--surface); color:var(--text); box-shadow:none; }
        .tuning-report-header .tuning-secondary:hover { transform:none; border-color:var(--primary); background:var(--surface-hover); box-shadow:none; }
        .tuning-report-status-slot { padding:0 var(--space-4) var(--space-3); }
        .tuning-report-status-slot:empty { display:none; }
        .tuning-report-status-slot .tuning-current-progress { width:100%; max-width:none; border-color:var(--border); border-radius:var(--radius-lg); background:var(--surface-alt); color:var(--text); box-shadow:none; }
        .tuning-report-status-slot .tuning-current-label, .tuning-report-status-slot .tuning-current-run-label { color:var(--text-muted); }
        .tuning-report-status-slot .tuning-current-run-id { color:var(--text-muted); }
        .tuning-report-tabs-host { padding:0 var(--space-4) var(--space-3); }
        .tuning-report-scroll {
          white-space:normal;
          height:min(74vh, 900px);
          min-height:520px;
          max-height:calc(100dvh - 180px);
          overflow:auto;
          resize:vertical;
          overscroll-behavior:contain;
          scroll-behavior:smooth;
          -webkit-overflow-scrolling:touch;
          padding:0 var(--space-4) var(--space-5);
          border:0;
          border-radius:0;
          background:var(--surface);
          color:var(--text);
        }
        .tuning-report-scroll:focus { outline:2px solid var(--primary-light); outline-offset:-2px; }
        .tuning-report-tablist { display:flex; gap:var(--space-1); width:max-content; max-width:100%; overflow-x:auto; padding:var(--space-1); border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface-alt); scrollbar-width:thin; }
        .tuning-report-tab { flex:0 0 auto; min-height:34px; padding:7px 11px; border:1px solid transparent; border-radius:var(--radius); background:transparent; color:var(--text-muted); font-weight:650; cursor:pointer; white-space:nowrap; }
        .tuning-report-tab:hover { background:var(--surface-hover); color:var(--text); }
        .tuning-report-tab[aria-selected="true"] { border-color:var(--border); background:var(--surface); color:var(--primary); }
        .tuning-report-tab:focus-visible { outline:2px solid var(--primary); outline-offset:1px; }
        .tuning-report-panels { min-width:0; }
        .tuning-report-panel { padding:var(--space-4) var(--space-1) var(--space-5); color:var(--text); line-height:1.65; }
        .tuning-report-panel[hidden] { display:none; }
        .tuning-report-panel h2 { margin:24px 0 10px; padding-bottom:7px; border-bottom:1px solid var(--border); color:var(--text); font-size:20px; }
        .tuning-report-panel h3 { margin:20px 0 8px; font-size:16px; }
        .tuning-report-panel p { margin:8px 0 14px; white-space:pre-wrap; overflow-wrap:anywhere; }
        .tuning-report-panel ul, .tuning-report-panel ol { margin:8px 0 16px; padding-left:24px; }
        .tuning-report-code { max-width:100%; margin:10px 0 18px; padding:14px; overflow:auto; border:1px solid #dbe3ef; border-radius:10px; background:#0f172a; color:#e2e8f0; white-space:pre; }
        .tuning-report-code code { font-family:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; font-size:12px; line-height:1.55; }
        .tuning-report-table { width:100%; margin:10px 0 20px; border-collapse:collapse; display:block; overflow-x:auto; white-space:nowrap; }
        .tuning-report-table th, .tuning-report-table td { padding:9px 11px; border:1px solid var(--border); text-align:left; }
        .tuning-report-table th { background:var(--surface-alt); font-weight:750; }
        .tuning-report-table tbody tr:nth-child(even) { background:var(--surface-alt); }
        .tuning-report-empty { padding:24px; border:1px dashed var(--border); border-radius:var(--radius-lg); color:var(--text-muted); text-align:center; }
        /* Visible ASTA inputs: let the rows attribute control initial height. */
        #asta-sql,
        #asta-tuning-notes {
          height:auto;
          min-height:0;
          overflow-y:auto;
        }
        @media (max-width: 1100px) {
          .tuning-grid { grid-template-columns:1fr; }
          .tuning-aside { position:static; }
          .tuning-controls-row { grid-template-columns:repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 720px) {
          .tuning-shell {
            min-height: calc(100dvh - 56px);
            margin: calc(var(--space-3, 12px) * -1);
            padding: 12px;
            background: #f7f8fb;
          }
          .tuning-hero {
            display:block;
            margin-bottom:12px;
          }
          .tuning-hero-actions, .tuning-top-actions { justify-content:flex-start; margin-top:8px; }
          .tuning-current-progress { width:100%; justify-content:flex-start; border-radius:14px; }
          .tuning-current-main { max-width:38vw; }
          .tuning-current-detail { max-width:42vw; }
          .tuning-kicker { font-size:11px; margin-bottom:8px; }
          .tuning-title {
            font-size: 28px;
            line-height: 1.08;
            letter-spacing: -0.6px;
          }
          .tuning-subtitle {
            margin-top:8px;
            font-size:13px;
            line-height:1.45;
          }
          .tuning-hero > .tuning-pill { display:none; }
          .tuning-grid { gap:12px; }
          .tuning-card {
            border-radius:16px;
            padding:12px;
            box-shadow:0 10px 26px rgba(15,23,42,.08);
          }
          .tuning-card-title { margin-bottom:10px; }
          .tuning-card-title .tuning-pill { display:none; }
          .tuning-controls-row { grid-template-columns:minmax(0, 1fr); gap:0; }
          .tuning-controls-row .tuning-field { margin-bottom:10px; }
          .tuning-field { gap:6px; margin-bottom:10px; }
          .tuning-field span { font-size:12px; }
          .tuning-input { padding:10px 11px; font-size:14px; }
          .tuning-sql-wrap {
            grid-template-columns: 1fr;
            border-radius:12px;
            overflow: visible;
          }
          .tuning-line-numbers {
            display:none;
          }
          .tuning-sql {
            height: 58dvh;
            min-height: 360px;
            max-height: none;
            padding:12px;
            font-size:12.5px;
            line-height:1.55;
            overflow:auto;
            -webkit-overflow-scrolling:touch;
          }
          .tuning-actions {
            display:grid;
            grid-template-columns:1fr;
            gap:8px;
          }
          .tuning-primary,
          .tuning-secondary {
            width:100%;
            min-height:44px;
            padding:11px 12px;
          }
          .tuning-aside {
            position:static;
          }
          .tuning-run-meta {
            grid-template-columns:1fr 1fr;
            gap:6px;
            padding:9px;
            margin-bottom:8px;
          }
          .tuning-run-meta b { font-size:10px; }
          .tuning-run-meta span { font-size:11px; }
          .tuning-step {
            gap:9px;
            padding:9px 0;
            font-size:12px;
            line-height:1.35;
          }
          .tuning-num {
            flex-basis:22px;
            width:22px;
            height:22px;
            border-radius:7px;
            font-size:11px;
          }
          .tuning-result { margin-top:12px; }
          .tuning-result .card { padding:12px !important; border-radius:16px; }
          .tuning-result .code-block {
            max-height: 62vh !important;
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap !important;
            overflow-wrap: anywhere;
          }
          .tuning-report-head { display:grid; grid-template-columns:1fr; }
          .tuning-report-actions { display:grid; grid-template-columns:1fr 1fr; width:100%; }
          .tuning-report-scroll {
            height:68dvh;
            min-height:440px;
            max-height:68dvh !important;
            white-space:normal !important;
            overflow-wrap:anywhere;
          }
          .tuning-report-tablist { width:100%; overflow-x:auto; flex-wrap:nowrap; }
          .tuning-report-panel { padding-inline:0; }
          .tuning-report-code { font-size:11px; }
        }
        @media (max-width: 700px) {
          .tuning-result .tuning-report-card { padding:0 !important; border-radius:var(--radius-lg); }
          .tuning-report-header { min-width:0; }
          .tuning-report-head { grid-template-columns:1fr; padding:var(--space-3) var(--space-3) var(--space-2); }
          .tuning-report-actions { grid-template-columns:1fr 1fr; gap:var(--space-2); }
          .tuning-report-status-slot { padding-inline:var(--space-3); padding-bottom:var(--space-3); }
          .tuning-report-status-slot .tuning-current-progress { align-items:flex-start; border-radius:var(--radius-lg); }
          .tuning-report-tabs-host { padding-inline:var(--space-3); padding-bottom:var(--space-3); }
          .tuning-report-tablist { width:100%; overflow-x:auto; flex-wrap:nowrap; }
          .tuning-report-tab { min-height:32px; padding:6px 10px; }
          .tuning-report-scroll { padding-inline:var(--space-3); padding-bottom:var(--space-4); }
          .tuning-report-panel { padding:var(--space-3) 0 var(--space-4); }
        }
        @media (max-width: 390px) and (orientation: portrait) {
          .tuning-shell {
            min-height: calc(100dvh - 50px);
            margin: -10px;
            padding: 10px;
          }
          .tuning-hero { margin-bottom: 10px; }
          .tuning-kicker { display:none; }
          .tuning-title { font-size: 24px; line-height: 1.05; letter-spacing: -0.45px; }
          .tuning-subtitle { font-size: 12px; line-height: 1.38; margin-top: 6px; }
          .tuning-card { padding: 10px; border-radius: 14px; }
          .tuning-card-title { font-size: 14px; margin-bottom: 8px; }
          .tuning-field { margin-bottom: 8px; }
          .tuning-input { padding: 9px 10px; font-size: 13px; }
          .tuning-sql-wrap { grid-template-columns: 1fr; border-radius: 10px; overflow: visible; }
          .tuning-line-numbers { display:none; }
          .tuning-sql {
            height: 60dvh;
            min-height: 340px;
            max-height: none;
            padding: 10px;
            font-size: 12px;
            line-height: 1.48;
          }
          .tuning-primary, .tuning-secondary { min-height: 42px; padding: 10px 11px; }
          .tuning-aside { max-height: 32dvh; overflow:auto; }
          .tuning-run-meta { grid-template-columns: 1fr 1fr; padding: 8px; }
          .tuning-step { padding: 7px 0; font-size: 11.5px; }
          .tuning-result .code-block { max-height: 56dvh !important; font-size: 11.5px; }
        }
        @media (max-height: 430px) and (orientation: landscape) {
          .tuning-shell {
            min-height: calc(100dvh - 46px);
            margin: -8px;
            padding: 8px;
          }
          .tuning-hero { display:none; }
          .tuning-grid { grid-template-columns: 1fr; gap: 8px; }
          .tuning-card { padding: 9px; border-radius: 12px; }
          .tuning-card-title { margin-bottom: 7px; font-size: 13px; }
          .tuning-field { gap: 5px; margin-bottom: 7px; }
          .tuning-field span { font-size: 11px; }
          .tuning-input { padding: 8px 9px; font-size: 12px; }
          .tuning-sql-wrap { grid-template-columns: 1fr; overflow: visible; }
          .tuning-line-numbers { display:none; }
          .tuning-sql {
            height: calc(100dvh - 190px);
            min-height: 170px;
            max-height: none;
            padding: 9px;
            font-size: 11.5px;
            line-height: 1.42;
          }
          .tuning-actions { grid-template-columns: 1fr 1fr; gap: 6px; }
          .tuning-primary, .tuning-secondary { min-height: 38px; padding: 8px 9px; font-size: 12px; }
          .tuning-aside { position: static; max-height: calc(100dvh - 62px); overflow:auto; }
          .tuning-run-meta { grid-template-columns: 1fr; gap: 4px; padding: 7px; margin-bottom: 6px; }
          .tuning-step { padding: 6px 0; gap: 7px; font-size: 11px; line-height: 1.25; }
          .tuning-num { flex-basis: 20px; width: 20px; height: 20px; font-size: 10px; }
          .tuning-result .code-block { max-height: 58dvh !important; font-size: 11px; }
        }
      </style>
      <section class="tuning-shell">
        <div class="tuning-hero">
          <div>
            <div class="tuning-kicker"><span class="tuning-dot"></span> ASTA Workspace</div>
            <h1 class="tuning-title">AI SQL Tuning Assistan<button id="asta-secret-trigger" class="tuning-secret-trigger" type="button" aria-label="Assistant 마지막 t">t</button></h1>
          </div>
          <div class="tuning-hero-actions">
            <div class="tuning-top-actions" aria-label="ASTA 빠른 작업">
              <button class="tuning-primary" id="asta-run" title="SQL Formatting 후 ADB ORDS/PLSQL AI 분석을 실행합니다">AI 분석 실행</button>
              <button class="tuning-secondary" id="asta-reset" type="button" hidden>신규분석(초기화)</button>
              <button class="tuning-secondary" id="asta-download-report" type="button" hidden>보고서 다운로드</button>
              <button class="tuning-secondary tuning-secret-only" id="asta-sql-only-llm" type="button" hidden title="SQL 텍스트만 선택한 LLM profile로 전송합니다">SQL만 LLM</button>
              <span id="asta-current-progress" class="tuning-progress-anchor" aria-live="polite"></span>
            </div>
          </div>
        </div>

        <div class="tuning-grid">
          <div class="tuning-card">
            <div class="tuning-card-title">
              <span>SQL 분석 입력</span>
              <span id="asta-advisor-status" class="tuning-advisor-state" role="status" aria-label="Oracle 튜닝 권고 사용 상태">Oracle 튜닝 권고: 사용 안 함</span>
            </div>
            <div class="tuning-controls-row">
              <label class="tuning-field" for="asta-ai-profile">
                <span>AI 모델 설정</span>
                <select class="tuning-input" id="asta-ai-profile">
                  <option value="ASTA_GROK_REASONING_PROFILE" selected>ASTA_GROK_REASONING_PROFILE</option>
                  <option value="ASTA_GROK_GENAI_PROFILE">ASTA_GROK_GENAI_PROFILE</option>
                  <option value="ASTA_GEMINI_PROFILE">ASTA_GEMINI_PROFILE</option>
                  <option value="ASTA_DB_GENAI_TEST">ASTA_DB_GENAI_TEST</option>
                </select>
              </label>
              <label class="tuning-field" for="asta-workload-type">
                <span>실행 유형</span>
                <select class="tuning-input" id="asta-workload-type">
                  <option value="OLTP" selected>OLTP — Buffer Reads 최소화</option>
                  <option value="BATCH">배치 — Elapsed Time 최소화</option>
                </select>
                <small id="asta-workload-description" class="muted">OLTP: Buffer Reads를 우선하며 채택 latency는 3초 이하, 기존 대비 증가는 300ms 이하입니다.</small>
              </label>
              <label class="tuning-field" for="asta-sample-sql">
                <span>샘플 튜닝대상 SQL</span>
                <select class="tuning-input" id="asta-sample-sql">
                  <option value="">직접 입력</option>
                  ${ASTA_SAMPLE_SQLS.map((sample) => `<option value="${escapeHtml(sample.id)}">${escapeHtml(sample.label)}</option>`).join("")}
                </select>
              </label>
            </div>
            <label class="tuning-field" for="asta-tuning-notes">
              <span>AI 참고사항 (선택)</span>
              <textarea class="tuning-input tuning-notes" id="asta-tuning-notes" rows="3" spellcheck="false" placeholder="예: 특정 테이블/인덱스/조건을 중점 검토, 업무상 유지해야 하는 조건, 의심 병목 등"></textarea>
            </label>
            <label class="tuning-field" for="asta-sql">
              <span>SQL</span>
              <textarea class="tuning-sql" id="asta-sql" rows="10" spellcheck="false" placeholder="SELECT ...">select * from dual</textarea>
            </label>
          </div>
        </div>

        <div id="asta-result" class="tuning-result stack"></div>
      </section>`;

    const profileInput = document.getElementById("asta-ai-profile");
    const workloadSelect = document.getElementById("asta-workload-type");
    const sampleInput = document.getElementById("asta-sample-sql");
    const notesInput = document.getElementById("asta-tuning-notes");
    const sqlInput = document.getElementById("asta-sql");
    const lineNumbers = document.getElementById("asta-line-numbers");
    const result = document.getElementById("asta-result");
    const progressTarget = document.getElementById("asta-current-progress");
    renderProgressStack(progressTarget, { status: "READY", progress: DEFAULT_STEPS });

    /**
     * SQL 입력/결과/진행률/옵션을 기본 상태로 초기화한다.
     */
    function resetWorkspace() {
      const runButton = document.getElementById("asta-run");
      const resetButton = document.getElementById("asta-reset");
      const downloadButton = document.getElementById("asta-download-report");
      const topActions = document.querySelector(".tuning-top-actions");
      const secretButton = document.getElementById("asta-sql-only-llm");
      if (topActions && resetButton && downloadButton) {
        topActions.insertBefore(resetButton, secretButton);
        topActions.insertBefore(downloadButton, secretButton);
        topActions.append(progressTarget);
      }
      window.__astaLastReport = null;
      window.__astaLastError = null;
      window.__astaRunStartedAt = null;
      workloadSelect.value = "OLTP";
      updateWorkloadDescription("OLTP");
      result.innerHTML = "";
      renderProgressStack(progressTarget, { status: "READY", progress: DEFAULT_STEPS });
      if (runButton) {
        runButton.disabled = false;
        runButton.textContent = "AI 분석 실행";
      }
      if (resetButton) resetButton.hidden = true;
      if (downloadButton) downloadButton.hidden = true;
    }

    function optimizationGoalForWorkload(workloadType) {
      return workloadType === "BATCH" ? "MINIMIZE_ELAPSED_TIME" : "MINIMIZE_BUFFER_READS";
    }

    function updateWorkloadDescription(workloadType) {
      const description = document.getElementById("asta-workload-description");
      if (!description) return;
      description.textContent = workloadType === "BATCH"
        ? "BATCH: 대량 처리의 전체 Elapsed Time 최소화를 우선합니다."
        : "OLTP: Buffer Reads를 우선하며 채택 latency는 3초 이하, 기존 대비 증가는 300ms 이하입니다.";
    }

    /**
     * ADB ORDS에서 선택 가능한 ASTA LLM 프로필 목록을 불러온다.
     */
    async function loadAstaProfiles() {
      try {
        const data = await fetchJson("/api/asta/profiles");
        const profiles = Array.isArray(data) ? data : (data.profiles || []);
        const astaProfiles = profiles
          .map((profile) => ({
            name: String(profile.profile_name || profile.name || "").trim(),
            label: String(profile.display_name || profile.profile_name || profile.name || "").trim(),
            model: String(profile.model || profile.model_name || "").trim(),
            provider: String(profile.provider || "").trim(),
            selectable: profile.selectable !== false,
            isDefault: profile.default === true || String(profile.profile_name || profile.name || "") === String(data.asta_default || ""),
          }))
          .filter((profile) => profile.name.toUpperCase().startsWith("ASTA") && profile.selectable)
          .sort((a, b) => a.name.localeCompare(b.name));
        if (!astaProfiles.length) return;
        const preferredProfile = astaProfiles.find((profile) => profile.name === DEFAULT_AI_PROFILE)
          || astaProfiles.find((profile) => profile.isDefault)
          || astaProfiles[0];
        profileInput.innerHTML = astaProfiles.map((profile) => {
          const meta = [profile.provider, profile.model].filter(Boolean).join(" / ");
          const text = meta ? `${profile.name} — ${meta}` : profile.name;
          return `<option value="${escapeHtml(profile.name)}" ${profile.name === preferredProfile.name ? "selected" : ""}>${escapeHtml(text)}</option>`;
        }).join("");
        if (!astaProfiles.some((profile) => profile.name === profileInput.value)) {
          profileInput.value = preferredProfile.name;
        }
      } catch (err) {
        console.warn("ASTA profile load failed", err);
        window.Toast?.show?.("ASTA profile 조회 실패: 기본 목록을 사용합니다.", "error");
      }
    }

    loadAstaProfiles();

    /**
     * 샘플 ID에 해당하는 ASTA 테스트 SQL을 에디터에 채운다.
     */
    function applySampleSql(sampleId) {
      const sample = ASTA_SAMPLE_SQLS.find((item) => item.id === sampleId);
      if (!sample) return;
      const workloadType = sample.workload || "OLTP";
      workloadSelect.value = workloadType;
      updateWorkloadDescription(workloadType);
      sqlInput.value = sample.sql;
      updateLineNumbers();
      window.Toast?.show?.("샘플 SQL을 입력창에 반영했습니다.", "success");
    }

    /**
     * SQL 에디터 줄 번호 영역을 갱신한다.
     */
    function updateLineNumbers() {}
    /**
     * SQL 에디터 스크롤과 줄 번호 스크롤을 동기화한다.
     */
    function syncLineNumberScroll() {}
    /**
     * SQL 에디터 표시 상태와 줄 번호를 다시 그린다.
     */
    function refreshSqlEditorPaint() {
      window.requestAnimationFrame(() => {
        sqlInput.style.transform = "translateZ(0)";
      });
    }
    sqlInput.addEventListener("input", refreshSqlEditorPaint);
    workloadSelect.addEventListener("change", () => updateWorkloadDescription(workloadSelect.value));
    sampleInput.addEventListener("change", () => applySampleSql(sampleInput.value));

    document.getElementById("asta-download-report").addEventListener("click", () => {
      if (!window.__astaLastReport?.rawReport) return;
      const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
      downloadText(`asta_tuning_report_${stamp}_${window.__astaLastReport.runId || "report"}.md`, window.__astaLastReport.rawReport);
    });
    document.getElementById("asta-reset").addEventListener("click", resetWorkspace);

    document.getElementById("asta-secret-trigger").addEventListener("click", () => {
      const secretButton = document.getElementById("asta-sql-only-llm");
      if (secretButton) {
        secretButton.hidden = !secretButton.hidden;
        window.Toast?.show?.(secretButton.hidden ? "숨김 LLM 기능을 닫았습니다." : "숨김 기능: SQL만 LLM 버튼을 열었습니다.", "success");
      }
    });

    document.getElementById("asta-sql-only-llm").addEventListener("click", async () => {
      const sql = stripTrailingSqlTerminator(sqlInput.value);
      if (!sql) {
        window.Toast?.show?.("SQL을 입력하세요.", "error");
        return;
      }
      const startedAt = new Date();
      window.__astaRunStartedAt = startedAt;
      renderProgressStack(progressTarget, buildClientProgress("RUNNING", startedAt, 6, startedAt, null, "SQL 텍스트만 LLM으로 전송 중"));
      result.innerHTML = '<div class="empty-state"><span class="tuning-spinner"></span> SQL만 LLM으로 전송 중...</div>';
      try {
        const oracleSqlOnlyPrompt = [
          "Oracle Database 기준으로 SQL 튜닝을 요청합니다.",
          "아래 SQL을 Oracle 옵티마이저 관점에서 분석하고, 실행 가능한 개선 SQL을 제안하세요.",
          "DML/DDL/PLSQL은 제안하지 말고 SELECT/WITH 단일문만 제안하세요.",
          "힌트만 추가하는 것보다 구조적 rewrite가 가능하면 우선 제안하세요.",
          "응답에는 병목 추정, 변경 이유, 개선 SQL, 주의사항을 한국어로 포함하세요.",
          "SQL:",
          sql,
        ].join("\n");
        const data = await fetchJson(`${DEFAULT_ORDS_BASE_URL}/llm-sql-only`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sql,
            sql_text: sql,
            prompt: oracleSqlOnlyPrompt,
            user_prompt: oracleSqlOnlyPrompt,
            tuning_context: {
              mode: "SQL_ONLY_LLM",
              workload_type: workloadSelect.value,
              optimization_goal: optimizationGoalForWorkload(workloadSelect.value),
              database: "Oracle Database",
              instruction: "Oracle 기준 SQL 튜닝 요청. SELECT/WITH 단일문 개선 SQL과 병목/변경 이유/주의사항을 한국어로 반환.",
            },
            ai_profile: profileInput.value || DEFAULT_AI_PROFILE,
            llm_profile: profileInput.value || DEFAULT_AI_PROFILE,
          }),
        });
        const endedAt = new Date();
        renderProgressStack(progressTarget, buildClientProgress("COMPLETED", startedAt, DEFAULT_STEPS.length - 1, startedAt, endedAt, "SQL-only LLM 완료"));
        renderResult(result, {
          ...data,
          run_id: `SQL_ONLY_${endedAt.toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}`,
          detailed_report_markdown: data.report_markdown || data.response || JSON.stringify(data, null, 2),
        });
      } catch (err) {
        const failedAt = new Date();
        renderError(result, err);
        renderProgressStack(progressTarget, buildClientProgress("FAILED", startedAt, 6, startedAt, failedAt, err.message));
        window.Toast?.show?.("SQL-only LLM 실패: " + err.message, "error", 15000);
      }
    });

    document.getElementById("asta-run").addEventListener("click", async () => {
      const runButton = document.getElementById("asta-run");
      const baseUrl = buildBaseUrl(DEFAULT_ENDPOINT);
      const url = buildAnalyzeUrl(DEFAULT_ENDPOINT);
      const sql = stripTrailingSqlTerminator(sqlInput.value);
      const userNotes = (notesInput?.value || "").trim();
      const formattedSql = formatSql(sql);
      const matchedSample = ASTA_SAMPLE_SQLS.find((sample) => formatSql(sample.sql) === formattedSql);
      if (!sql) {
        window.Toast?.show?.("SQL을 입력하세요.", "error");
        return;
      }
      sqlInput.value = formattedSql;
      updateLineNumbers();
      const startedAt = new Date();
      window.__astaRunStartedAt = startedAt;
      let stepStartedAt = startedAt;
      let stepIndex = 0;
      const stepDetails = [
        "요청 수신",
        "ADB ORDS/PLSQL 동기 분석 실행 중 — 세부 단계별 이력은 완료 후 실제 DB progress로 표시됩니다",
        "SQL 안전성 검사",
        "원본 SQL Evidence 수집: metrics, SQL_ID, XPLAN, object 통계",
        "SQL Advisor 생략 (기본 OFF)",
        "ADB Vector KB 유사 결과서 조회",
        "AI 1차 튜닝: 분석결과 + Vector 사례 참조",
        "튜닝 SQL 분석: 튜닝 SQL 재수행/비교",
        "AI Before/After 정리",
        "최종 보고서 생성",
        "ADB Vector KB 결과서 저장",
      ];
      runButton.disabled = true;
      runButton.textContent = "분석중";
      const progressTimer = window.setInterval(() => {
        const elapsed = Date.now() - startedAt.getTime();
        const nextIndex = 1;
        if (nextIndex !== stepIndex) {
          stepIndex = nextIndex;
          stepStartedAt = new Date();
        }
        renderProgressStack(progressTarget, buildClientProgress("RUNNING", startedAt, stepIndex, stepStartedAt, null, stepDetails[stepIndex]));
      }, 500);
      renderProgressStack(progressTarget, buildClientProgress("RUNNING", startedAt, 0, stepStartedAt, null, stepDetails[0]));
      result.innerHTML = '<div class="empty-state"><span class="tuning-spinner"></span> ADB ORDS/PLSQL 기반 AI 분석 실행 중...</div>';
      let completedOk = false;
      try {
        const sourceId = DEFAULT_SOURCE_ID;
        const data = await fetchJson(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sql_text: formattedSql,
            sql: formattedSql,
            source_sql_id: matchedSample?.sqlId || null,
            source_db_id: sourceId,
            ai_profile: profileInput.value || DEFAULT_AI_PROFILE,
            llm_profile: profileInput.value || DEFAULT_AI_PROFILE,
            use_llm: true,
            // 사용자 결정에 따라 일반 실행은 기본 OFF다. 명시적 API true opt-in 기능은 유지한다.
            run_advisor: false,
            use_sqltune: false,
            sqltune_time_limit: 1800,
            tuning_context: {
              workload_type: workloadSelect.value,
              optimization_goal: optimizationGoalForWorkload(workloadSelect.value),
              user_notes: userNotes,
              source: "UI_OPTIONAL_TEXT",
              instruction: userNotes ? "사용자 참고사항을 SQL 튜닝 후보 생성과 최종 결과서 판단에 우선 참고하되, 실제 실행 evidence와 충돌하면 evidence를 우선한다." : "",
            },
            options: {
              fetch_rows: 100,
              timeout_seconds: 900,
              sqltune_time_limit: 1800,
              run_advisor: false,
              use_sqltune: false,
              run_mode: "ASYNC",
              use_llm: true,
              llm_profile: profileInput.value || DEFAULT_AI_PROFILE,
            },
          }),
        });
        if (["FAILED", "ERROR"].includes(String(data?.status || "").toUpperCase())) {
          const immediateMessage = data?.error_message || data?.error?.message || data?.message || data?.error_code || "ASTA 요청이 실패했습니다.";
          const immediateError = new Error(immediateMessage);
          immediateError.progress = data;
          throw immediateError;
        }
        window.clearInterval(progressTimer);
        if (data?.run_id && ["RUNNING", "QUEUED"].includes(String(data?.status || "").toUpperCase())) {
          renderProgressStack(progressTarget, { ...data, totalDurationMs: Date.now() - startedAt.getTime() });
          const terminalProgress = await pollRunProgress(baseUrl, data.run_id, progressTarget, result);
          Object.assign(data, terminalProgress || {});
        } else {
          const endedAt = new Date();
          let finalProgress = null;
          const proxySource = String(data?.proxy?.source || "").toUpperCase();
          const hasAuthoritativeInlineProgress = proxySource.includes("SOURCE_DIRECT_FALLBACK") || proxySource.includes("CONTROLLED_FALLBACK");
          if (data?.run_id && !hasAuthoritativeInlineProgress) {
            const encodedRunId = encodeURIComponent(data.run_id);
            try { finalProgress = await fetchJson(`${baseUrl}/runs/${encodedRunId}/progress`); } catch (_) { finalProgress = null; }
          } else if (data?.run_id && hasAuthoritativeInlineProgress) {
            console.warn("asta-progress-stale-ords-suppressed", {
              run_id: data.run_id,
              proxy_source: data?.proxy?.source || "",
              inline_status: data?.status || "",
            });
          }
          const inlineOutcome = astaWorkflowOutcome({ ...data, ...(finalProgress || {}) });
          if (finalProgress?.progress || finalProgress?.steps) {
            renderProgressStack(progressTarget, { ...finalProgress, status: inlineOutcome, startedAt, endedAt, totalDurationMs: endedAt - startedAt });
          } else if (data?.progress || data?.steps) {
            renderProgressStack(progressTarget, { ...data, status: inlineOutcome, startedAt, endedAt, totalDurationMs: endedAt - startedAt });
          } else {
            renderProgressStack(progressTarget, buildClientProgress(inlineOutcome === "ACCEPTED" ? "COMPLETED" : "FAILED", startedAt, DEFAULT_STEPS.length - 1, stepStartedAt, endedAt, inlineOutcome === "ACCEPTED" ? "완료" : "추가 확인이 필요합니다"));
          }
          renderResult(result, data);
        }
        const terminalOutcome = astaWorkflowOutcome(data);
        if (terminalOutcome === "ACCEPTED") {
          runButton.textContent = "완료";
          completedOk = true;
          window.Toast?.show?.("ASTA 분석이 완료되었습니다.", "success");
        } else {
          const issue = friendlyAstaIssue(data, terminalOutcome);
          runButton.textContent = "확인 필요";
          completedOk = false;
          window.Toast?.show?.(`${issue.title}: ${issue.message}`, "error", 15000);
        }
      } catch (err) {
        window.clearInterval(progressTimer);
        const failedAt = new Date();
        renderError(result, err);
        if (err?.progress) {
          renderProgressStack(progressTarget, {
            ...err.progress,
            status: "FAILED",
            totalDurationMs: failedAt - startedAt,
          });
        } else {
          renderProgressStack(progressTarget, buildClientProgress("FAILED", startedAt, stepIndex, stepStartedAt, failedAt, err.message));
        }
        const issue = err?.friendlyIssue || friendlyAstaIssue(err?.progress || err?.payload || err, err?.message);
        runButton.textContent = "다시 분석";
        window.Toast?.show?.(`${issue.title}: ${issue.message}`, "error", 15000);
      } finally {
        if (!completedOk) runButton.disabled = false;
      }
    });
  };
})();
