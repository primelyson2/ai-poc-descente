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
    ...(() => {
      const baseMetrics = [
        ["TOTAL_QTY", "SUM(SALE_QTY)"],
        ["TOTAL_AMT", "SUM(SALE_AMT)"],
        ["REAL_AMT", "SUM(REAL_SALE_AMT)"],
        ["COST_AMT", "SUM(SALE_COST_AMT)"],
        ["STD3_QTY", "SUM(CASE WHEN SALE_STD_CD='3' THEN SALE_QTY ELSE 0 END)"],
        ["KIND1_QTY", "SUM(CASE WHEN SALE_KIND_CD='1' THEN SALE_QTY ELSE 0 END)"],
        ["BSAL23_AMT", "SUM(CASE WHEN BSAL_CLS_CD IN ('2','3') THEN SALE_AMT ELSE 0 END)"],
        ["NORMAL_QTY", "SUM(CASE WHEN NOR_CLS_CD='1' THEN SALE_QTY ELSE 0 END)"],
      ];
      const metrics = [1, 2, 3, 4, 5].flatMap((section) =>
        baseMetrics.map(([name, expression]) => [`S${section}_${name}`, expression])
      );
      const definitions = [
        ["asta-batch-01", "B01 · 브랜드 KPI 반복 집계", "BATCH_BRAND_KPI_RESCAN", "BRAND_CD"],
        ["asta-batch-02", "B02 · 상품분류 KPI 반복 집계", "BATCH_CLASS_KPI_RESCAN", "CLASS_CD"],
        ["asta-batch-03", "B03 · 성별 KPI 반복 집계", "BATCH_GENDER_KPI_RESCAN", "GENDER_CD"],
        ["asta-batch-04", "B04 · 라인 KPI 반복 집계", "BATCH_LINE_KPI_RESCAN", "LINE_CD"],
        ["asta-batch-05", "B05 · 판매기준 KPI 반복 집계", "BATCH_SALE_STANDARD_KPI_RESCAN", "SALE_STD_CD"],
      ];
      const filter = "COMP_CD='01' AND SALE_DE BETWEEN '20250101' AND '20251231'";
      const buildSql = (dimension) => metrics.map(([name, expression]) =>
        `SELECT ${dimension}, '${name}' METRIC, ${expression} METRIC_VALUE\n` +
        `FROM DSNT.TSE_SALE_DAY_S WHERE ${filter} GROUP BY ${dimension}`
      ).join("\nUNION ALL\n");
      return definitions.map(([id, label, pattern, dimension]) => ({
        id,
        label,
        pattern,
        workload: "BATCH",
        sql: buildSql(dimension),
      }));
    })(),
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
  const ASTA_ARCHITECTURE_ZONES = Object.freeze([
    {
      key: "user",
      eyebrow: "요청과 의사결정",
      title: "User / 개발자",
      compartment: "PoC 샘플 화면",
      boundary: "운영 SQL 자동 변경 없음",
      resources: [],
      functions: [
        "PoC용 SELECT/WITH 샘플 또는 테스트 SQL 입력",
        "진행 상태와 Run ID 확인, 결과서 6개 탭 검토",
        "IMPROVED 후보도 코드 리뷰·업무 테스트·배포 승인 후 반영",
      ],
    },
    {
      key: "ui",
      eyebrow: "OADT2 Application",
      title: "UI (VM)",
      compartment: "DEV compartment",
      boundary: "FastAPI thin proxy",
      resources: [
        { type: "Network", name: "OCI Load Balancer", detail: "HTTPS listener·backend health check → DK-AI-DEV-VM-01" },
        { type: "Compute", name: "DK-AI-DEV-VM-01", detail: "OADT2 static UI, FastAPI, 인증·감사" },
      ],
      functions: [
        "브라우저 입력·샘플·진행 Drawer·결과서 안전 DOM 표시",
        "same-origin /api/asta 요청, 인증, payload 정규화와 audit",
        "ADB ORDS 제출·조회 중계만 수행하며 SQL/LLM을 로컬 실행하지 않음",
      ],
    },
    {
      key: "lakehouse",
      eyebrow: "Control & AI Plane",
      title: "OCI AI Lakehouse",
      compartment: "DEV compartment · Shared / Regional OCI Services",
      boundary: "ORDS · ADB PL/SQL · DBMS_SCHEDULER",
      resources: [
        { type: "Database", name: "Autonomous Database 26ai", detail: "ASTA schema, repository, Scheduler" },
        { type: "API", name: "ORDS asta.v1", detail: "submit, progress, run, report endpoint" },
        { type: "Data", name: "ASTA Vector KB", detail: "검증 사례와 rejected observation" },
        { type: "AI", name: "OCI Generative AI", detail: "AI profile 기반 regional inference" },
        { type: "Identity", name: "OCI IAM", detail: "Dynamic Group, Policy, Resource Principal" },
        { type: "Network", name: "VCN / Subnet / NSG", detail: "VM·ADB·BaseDB 접근과 routing 경계" },
      ],
      functions: [
        "ASTA_RUNS/PROGRESS 영속화와 비동기 Scheduler orchestration",
        "SQL Guard, AI 후보 생성, Vector 사례 검색·저장",
        "full-result·optimizer intent·bind·반복 측정 gate와 결과서 생성",
      ],
    },
    {
      key: "basedb",
      eyebrow: "Evidence Plane",
      title: "OCI ERP Database (BaseDB)",
      compartment: "PRO compartment",
      boundary: "DB Link · ASTA_SOURCE_PKG",
      resources: [
        { type: "Database", name: "OCI ERP Database (BaseDB)", detail: "업무 SQL 실행 Source DB/PDB" },
        { type: "Connection", name: "Allowlisted DB Link", detail: "logical Source ID 연결" },
        { type: "PL/SQL", name: "ASTA_SOURCE_PKG", detail: "XPLAN·metrics·full-result digest" },
        { type: "Schema", name: "ERP 업무 Schema", detail: "DSNT 업무 객체와 dictionary evidence" },
      ],
      functions: [
        "원본/후보 SQL bounded 실행과 warm-up 1회·측정 3회",
        "Oracle cursor metrics, 실행계획(XPLAN), bind/child cursor, 객체 통계 수집",
        "전체 결과 typed digest와 선택적 SQL Tuning Advisor 수행",
      ],
    },
  ]);
  const ASTA_WORKFLOW_GUIDE = Object.freeze([
    {
      seq: 1,
      code: "REQUEST_RECEIVED",
      title: "요청 수신",
      zone: "User / 개발자 → UI (VM) → OCI AI Lakehouse",
      procedure: "FastAPI asta_proxy.analyze → ASTA_PKG.SUBMIT_RUN",
      tasks: [
        "브라우저가 SQL 끝의 세미콜론을 정리하고 SQL·workload·AI profile·참고사항을 same-origin /api/asta/analyze로 보낸다.",
        "FastAPI가 허용된 payload만 남기고 임의 DB Link 입력을 제거한 뒤 고유 Run ID와 client_run_id를 만든다.",
        "요청 감사 로그에는 SQL 원문 대신 Run ID prefix와 fingerprint를 기록하고 ORDS ASTA_PKG.SUBMIT_RUN으로 전달한다.",
        "ADB가 SQL 필수값과 Run ID/idempotency 충돌을 확인하고 ASTA_RUNS에 request_json과 QUEUED 상태를 저장한다.",
      ],
      evidence: "ADB가 ASTA_RUNS에 request_json과 QUEUED 상태를 저장한다. 이 단계는 접수 marker이며 성능 판정은 하지 않는다.",
      failure: "요청 형식이나 필수 SQL이 없으면 실행 전에 거절한다.",
    },
    {
      seq: 2,
      code: "ORDS_DISPATCH",
      title: "분석 서버 연결",
      zone: "OCI AI Lakehouse",
      procedure: "ASTA_PKG.EXECUTE_RUN / RUN_PIPELINE",
      tasks: [
        "SUBMIT_RUN이 Run별 DBMS_SCHEDULER job 이름을 만들고 commit 후 job을 enable한다.",
        "브라우저에는 QUEUED/RUNNING을 즉시 반환해 긴 분석을 HTTP 요청과 분리하고 1초 간격 progress 조회를 시작한다.",
        "Scheduler가 EXECUTE_RUN을 호출해 저장된 request_json을 읽고 해당 Run을 한 번만 RUNNING으로 claim한다.",
        "private RUN_PIPELINE이 Source 연결·LLM·검증·결과서 단계를 순차 조정하며 각 시작/완료 시간을 ASTA_RUN_PROGRESS에 기록한다.",
      ],
      evidence: "ASTA_RUNS가 QUEUED에서 RUNNING으로 바뀌고 job_name·submitted_at·started_at을 보존한다.",
      failure: "job 생성이나 run claim 실패는 SUBMIT_RUN/EXECUTE_RUN 오류로 영속화한다.",
    },
    {
      seq: 3,
      code: "SQL_GUARD",
      title: "입력 SQL 확인",
      zone: "OCI AI Lakehouse",
      procedure: "ASTA_SQL_GUARD_PKG.ASSERT_SAFE_SELECT",
      tasks: [
        "입력 앞부분이 SELECT 또는 WITH인지 확인하고 주석·문자열을 제외한 실제 SQL 구조를 검사한다.",
        "세미콜론으로 연결된 다중 문장, INSERT·UPDATE·DELETE·MERGE, DDL, PL/SQL과 FOR UPDATE를 차단한다.",
        "SUBMIT_RUN 접수 시 한 번, RUN_PIPELINE의 Source 실행 직전에 다시 검사해 저장 후 변조 가능성도 차단한다.",
        "통과한 SQL만 allowlisted Source DB Link 실행 경계로 전달하며 Guard 자체는 SQL을 실행하지 않는다.",
      ],
      evidence: "SUBMIT_RUN과 RUN_PIPELINE에서 중복 검증해 저장 전과 실행 직전의 경계를 모두 보호한다.",
      failure: "SQL_GUARD_REJECTED로 종료하고 Source DB에는 SQL을 보내지 않는다.",
    },
    {
      seq: 4,
      code: "BEFORE_EVIDENCE",
      title: "원본 SQL 예상/실행 정보 수집",
      zone: "OCI AI Lakehouse ↔ OCI ERP Database (BaseDB)",
      procedure: "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE → ASTA_SOURCE_PKG.RUN_EVIDENCE_STORE_PROC / ASTA_SOURCE_PKG.RUN_EVIDENCE",
      tasks: [
        "logical source_db_id를 ASTA_SOURCE_CONNECTIONS allowlist에서 조회해 Source schema와 DB Link를 결정한다.",
        "기본 안전 모드는 업무 SELECT를 실행하지 않고 EXPLAIN PLAN 예상계획과 PLAN_TABLE object의 통계·인덱스만 수집한다.",
        "사용자가 실제 실행 체크박스를 켠 경우에만 MINIMAL 제한 실행 1회와 FULL_RESULT count/digest를 수행한다.",
        "미실행 모드는 source_sql_executed=false와 plan_kind=ESTIMATED를 남겨 LLM과 결과서가 실측으로 오해하지 않게 한다.",
      ],
      evidence: "기본은 예상 Plan·object 정보, 실행 opt-in은 XPLAN·Buffer Gets·elapsed와 결과/metadata digest를 JSON CLOB으로 회수한다.",
      failure: "DB Link, 권한, SQL 실행 또는 evidence 오류가 있으면 뒤 단계를 성공으로 추정하지 않는다.",
    },
    {
      seq: 5,
      code: "SQL_TUNING_ADVISOR",
      title: "Oracle 튜닝 권고",
      zone: "OCI ERP Database (BaseDB)",
      procedure: "ASTA_SOURCE_PKG.RUN_ADVISOR_OPT / ASTA_SOURCE_PKG.RUN_ADVISOR_JOB",
      tasks: [
        "사용자가 run_advisor/use_sqltune을 명시적으로 켰는지 확인하며 일반 ASTA 화면 기본값은 OFF다.",
        "활성화된 경우 4단계 Source 호출 안에서 DBMS_SQLTUNE task를 만들고 지정 시간 한도로 SQL Tuning Advisor를 실행한다.",
        "권고 report를 CLOB evidence로 회수하고 임시 task/job cleanup 상태까지 기록한다.",
        "5단계 progress는 별도 재실행이 아니라 4단계 Source response의 advisor.status를 DONE·SKIPPED·FAILED로 표시한다.",
      ],
      evidence: "4단계 Source response의 advisor.status를 ASTA_RUN_PROGRESS 5단계에 반영한다.",
      failure: "SKIPPED/FAILED여도 deterministic 후보 검증은 가능한 범위에서 계속하며 권고를 자동 적용하지 않는다.",
    },
    {
      seq: 6,
      code: "LLM_REWRITE",
      title: "개선 SQL 만들기",
      zone: "OCI AI Lakehouse",
      procedure: "ASTA_LLM_PKG.GENERATE_SQL_ONLY_TUNING",
      tasks: [
        "DIAGNOSIS: 원본 SQL·Plan·workload·사용자 참고사항으로 병목과 localized rewrite 전략·위험을 JSON으로 만든다. 미실행 모드는 Cost/Cardinality 추정만 사용하고 A-Time/Buffer/Starts 실측을 주장하지 않는다.",
        "CANDIDATE_SQL: diagnosis·원본 SQL·전체 XPLAN으로 실행 가능한 Oracle SELECT/WITH 한 문장만 생성한다. profile fallback은 최대 4회다.",
        "출력 컬럼·순서·datatype, predicate/JOIN, row grain·중복, NULL·집계 의미와 CTE/alias/컬럼 name resolution을 보존하도록 prompt에서 사전 점검한다.",
        "32,767자 한도, NO_REWRITE, 원본과 동일/comment-only/hint-only 여부와 SQL Guard를 검사하고 통과한 후보에 변경 주석을 보장한다. 정상 LLM 호출은 보통 2회, fallback 포함 최대 6회다.",
      ],
      evidence: "DIAGNOSIS/CANDIDATE_SQL별 attempt·profile·status를 ASTA_LLM_CALL_LOG에 남기고 candidate SQL·change summary·semantic risk를 artifact로 만든다.",
      failure: "안전한 후보가 없으면 NO_REWRITE로 원본을 유지한다. LLM 설명만으로 개선 성공을 선언하지 않는다.",
    },
    {
      seq: 7,
      code: "AFTER_EVIDENCE",
      title: "개선 SQL 안전성·성능 확인",
      zone: "OCI AI Lakehouse ↔ OCI ERP Database (BaseDB)",
      procedure: "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE / ASTA_LLM_PKG.REPAIR_SQL_CANDIDATE",
      tasks: [
        "후보 SQL에서 ANSI JOIN과 구식 (+) 외부 조인이 혼용되면 ORA-25156 사전 검사로 Source 실행 전에 차단한다.",
        "기본 미실행 모드는 후보도 EXPLAIN PLAN만 생성한다. 실제 실행 체크 시에만 PLAN_ONLY·ONCE로 XPLAN, Elapsed, Buffer Gets와 optimizer intent를 확인한다.",
        "PLAN_ONLY에서 workload 기준 성능과 optimizer intent를 통과한 후보만 AUTO·FULL_RESULT로 반복 측정과 전체 결과 count/digest를 수행한다.",
        "watchdog은 PLAN_ONLY 1회와 정밀 검증 최대 6회를 구분해 총 실행예산을 계산한다. ALTER SYSTEM을 사용하지 않으므로 timeout에는 ADB parent job만 종료한다.",
      ],
      evidence: "PLAN_ONLY screen 판정과 통과 후보의 XPLAN, 반복 metrics, 전체 결과 digest, optimizer intent와 bind evidence를 수집한다.",
      failure: "timeout·Oracle 오류·repair 실패는 CANDIDATE_FAILED 또는 CANDIDATE_RUNTIME_LIMIT로 원본을 유지한다.",
    },
    {
      seq: 8,
      code: "BEFORE_AFTER_COMPARE",
      title: "원본과 개선 결과 비교",
      zone: "OCI AI Lakehouse",
      procedure: "ASTA_PKG.BUILD_COMPARISON_JSON",
      tasks: [
        "후보가 의도한 반복 subtree 제거·Starts 감소·ANTI/set-operation 구조를 실제 Before/After XPLAN에서 먼저 확인한다.",
        "전체 결과 mode, 컬럼 metadata digest, 행 수와 result digest가 모두 같은지 검사하며 일부 결과만 있으면 fail-closed 처리한다.",
        "bind bucket별 plan family·shape·Starts 안정성과 Before/After 동일 bind 집합을 확인한다.",
        "반복 측정 완전성·noise·Buffer Gets와 workload별 절대/상대 elapsed 기준을 순서대로 적용해 최종 verdict와 reason을 결정한다.",
      ],
      evidence: "IMPROVED, ANALYSIS_ONLY, NOT_IMPROVED, NON_EQUIVALENT, INSUFFICIENT_EVIDENCE, CANDIDATE_FAILED, NO_REWRITE 중 하나와 reason을 만든다.",
      failure: "앞 gate가 불완전하면 뒤의 좋은 성능 수치만으로 채택하지 않는 fail-closed 방식이다.",
    },
    {
      seq: 9,
      code: "VECTOR_KB",
      title: "비슷한 튜닝 사례 찾기",
      zone: "OCI AI Lakehouse",
      procedure: "ASTA_VECTOR_PKG.SEARCH_SIMILAR_CASES",
      tasks: [
        "화면 번호는 9지만 LLM 후보 생성 전에 현재 SQL fingerprint/embedding으로 Vector 검색을 먼저 수행한다.",
        "gate-complete POSITIVE_VERIFIED 사례만 검색 대상으로 삼고 similarity와 allowlist metadata를 반환한다.",
        "raw SQL·literal·bind 값은 Vector metadata에 저장하거나 검색 결과로 노출하지 않는다.",
        "현재 구현은 검색 결과를 artifact로 보존하지만 generate_sql_only_tuning prompt에는 p_vector_json을 넣지 않아 6단계 후보 생성에는 아직 사용하지 않는다.",
      ],
      evidence: "유사도, 안전한 요약과 내부 report 경로를 Vector search artifact로 남기며 응답에는 vector_evidence_included=false가 기록된다.",
      failure: "유사 사례가 없어도 분석은 계속된다. 과거 사례만으로 현재 후보를 채택하지 않는다.",
    },
    {
      seq: 10,
      code: "FINAL_REPORT",
      title: "결과서 만들기",
      zone: "OCI AI Lakehouse → UI (VM)",
      procedure: "ASTA_REPORT_PKG.BUILD_REPORT / BUILD_RESPONSE_JSON",
      tasks: [
        "deterministic comparison verdict와 동일한 결론으로 Markdown 결과서 초안을 만든다. ANALYSIS_ONLY는 미실행 분석 완료이며 성능 개선 성공/실패가 아니다.",
        "결론·병목·전후 수치·전후 SQL/XPLAN 요약·객체정보·사용자 참고사항·실패 reason을 섹션별로 구성한다.",
        "11단계 Vector 저장 결과와 terminal progress timing을 포함하도록 마지막에 결과서를 다시 구성한다.",
        "BUILD_RESPONSE_JSON으로 report와 allowlist artifact를 API JSON에 묶고 ASTA_RUNS의 최종 status·tuned_sql·report·response를 영속화한다.",
      ],
      evidence: "결론, 전후 SQL/XPLAN, SQL 변경, 상세 분석, 객체정보와 11단계 timing을 ASTA_RUNS에 저장한다.",
      failure: "rich response 저장 실패도 RUNNING으로 방치하지 않고 ASTA_PERSIST 실패로 종결한다.",
    },
    {
      seq: 11,
      code: "VECTOR_SAVE",
      title: "검증 결과 저장",
      zone: "OCI AI Lakehouse",
      procedure: "ASTA_VECTOR_PKG.SAVE_CASE",
      tasks: [
        "8단계 verdict와 intent/full-result/bind/measurement gate가 모두 완료됐는지 다시 확인한다.",
        "모든 필수 gate를 통과한 개선만 POSITIVE_VERIFIED로 분류하고 검색 가능한 positive 영역에 저장한다.",
        "NO_REWRITE·ORA·비동등·bounded evidence·timeout·plan flip은 REJECTED_OBSERVATION으로 분리 저장한다.",
        "원본/후보 SQL과 bind 값은 저장하지 않고 reason code·안전한 수치·내부 report 경로 등 allowlist metadata만 보존한다.",
      ],
      evidence: "모든 필수 gate를 통과한 사례만 positive verified 검색 대상이 되며 결과서 참조는 내부 API 경로를 사용한다.",
      failure: "Vector 저장 실패는 결과서에 evidence로 남지만 기존 comparison verdict를 성공으로 바꾸지 않는다.",
    },
  ]);
  const ASTA_DEVELOPER_PLATFORMS = Object.freeze([
    {
      title: "브라우저 / 프런트엔드",
      role: "입력 검증, payload 생성, 비동기 진행 조회, 안전한 결과서 표시와 로컬 Markdown 저장",
      files: [
        "static/js/extensions/tuning_assistant.js",
        "static/js/extensions/asta_report_tabs.js",
      ],
      symbols: [
        "tuningAssistant", "formatSql", "stripTrailingSqlTerminator", "fetchJson",
        "pollRunProgress", "fetchReport", "renderResult", "downloadText",
        "classifyReportSections", "renderSafeMarkdown", "renderReportTabs",
      ],
      boundary: "브라우저는 Source DB나 외부 ORDS를 직접 호출하지 않고 same-origin /api/asta만 사용한다.",
    },
    {
      title: "애플리케이션 / API 서버",
      role: "인증된 same-origin 요청을 정규화하고 ORDS에 전달하며 run/progress/report 조회를 감사한다.",
      files: ["app/main.py", "app/routers/asta_proxy.py", "app/asta_audit.py"],
      symbols: [
        "analyze", "_coerce_payload", "_post_json_to_ords", "_audited_run_lookup",
        "get_run_progress", "get_run_report", "download_run_report",
      ],
      boundary: "FastAPI는 thin proxy다. Source SQL 실측, AI 호출, 비교 판정, 결과서 생성은 Python에서 수행하지 않는다.",
    },
    {
      title: "ORDS adapter",
      role: "HTTP handler를 ADB PL/SQL 함수에 연결하고 JSON CLOB을 chunked response로 반환한다.",
      files: ["db/ords/asta_ords_module.sql"],
      symbols: ["ASTA_PKG.SUBMIT_RUN", "ASTA_PKG.GET_PROGRESS", "ASTA_PKG.GET_RUN", "ASTA_PKG.GET_REPORT"],
      boundary: "ORDS module asta.v1은 adapter이며 분석 로직이나 verdict를 만들지 않는다.",
    },
    {
      title: "Target ADB / orchestration",
      role: "run 영속화, Scheduler, SQL Guard, Source bridge, Vector, LLM, deterministic gate, report를 조정한다.",
      files: [
        "db/adb/asta_pkg.sql", "db/adb/asta_source_bridge_pkg.sql", "db/adb/asta_llm_pkg.sql",
        "db/adb/asta_vector_pkg.sql", "db/adb/asta_report_pkg.sql",
      ],
      symbols: [
        "submit_run", "execute_run", "run_pipeline", "record_progress", "build_comparison_json",
        "run_source_evidence", "get_connection_json", "generate_sql_only_tuning", "repair_sql_candidate",
        "search_similar_cases", "save_case", "build_report", "build_response_json",
      ],
      boundary: "ASTA_RUNS/ASTA_RUN_PROGRESS가 상태의 기준이며 DBMS_SCHEDULER.CREATE_JOB으로 장기 실행을 브라우저와 분리한다.",
    },
    {
      title: "Source DB / 실측",
      role: "실행 opt-in에서는 업무 SQL을 실행해 cursor metric, XPLAN, bind/child cursor 및 full-result digest를 만들고, 기본 미실행 모드에서는 EXPLAIN PLAN과 객체정보만 만든다.",
      files: ["db/source/asta_source_pkg.sql"],
      symbols: [
        "run_evidence_store_proc", "run_evidence", "collect_metrics", "collect_xplan",
        "collect_object_info", "build_full_count_sql", "build_full_digest_sql",
        "DBMS_XPLAN.DISPLAY_CURSOR", "DBMS_SQLTUNE",
      ],
      boundary: "allowlisted DB Link로 호출된 ASTA_SOURCE_PKG만 실측한다. DML/DDL이나 권고 자동 적용은 하지 않는다.",
    },
    {
      title: "AI / LLM",
      role: "Source evidence와 Vector 사례, workload, 사용자 참고사항으로 구조적 SQL 후보를 생성하고 제한적으로 repair한다.",
      files: ["db/adb/asta_llm_pkg.sql"],
      symbols: ["ASTA_LLM_PKG.GENERATE_SQL_ONLY_TUNING", "ASTA_LLM_PKG.REPAIR_SQL_CANDIDATE", "DBMS_CLOUD_AI.GENERATE"],
      boundary: "LLM 출력은 후보일 뿐이다. Source 재실측과 deterministic gate를 통과하기 전에는 채택되지 않는다.",
    },
  ]);
  const ASTA_DEVELOPER_CALL_FLOW = Object.freeze([
    { n: 1, call: "stripTrailingSqlTerminator / formatSql", where: "Browser · tuning_assistant.js", detail: "빈 SQL을 차단하고 마지막 세미콜론 하나를 제거한 뒤 formatting한다. 원문 의미를 바꾸는 서버 판정은 하지 않는다." },
    { n: 2, call: "POST /api/asta/analyze", where: "Browser → FastAPI", detail: "sql/sql_text, logical source_db_id, profile, workload, 참고사항과 ASYNC option을 JSON으로 보낸다." },
    { n: 3, call: "asta_proxy.analyze", where: "app/routers/asta_proxy.py", detail: "_coerce_payload로 입력을 정규화하고 run_id를 만든 뒤 _post_json_to_ords로 ORDS 제출 응답을 받는다." },
    { n: 4, call: "ASTA_PKG.SUBMIT_RUN", where: "ORDS asta.v1 → Target ADB", detail: "SQL Guard, idempotency/run 충돌을 확인하고 ASTA_RUNS에 QUEUED를 저장한 뒤 Scheduler job을 enable한다." },
    { n: 5, call: "ASTA_PKG.EXECUTE_RUN", where: "Target ADB · DBMS_SCHEDULER", detail: "QUEUED/RETRY row를 잠가 RUNNING으로 바꾸고 저장된 request_json을 읽는다." },
    { n: 6, call: "ASTA_PKG.RUN_PIPELINE", where: "Target ADB", detail: "1~11 호환 progress를 기록하며 실제 의존 순서 3→4→5→9→6→7→8→11→10을 조정한다." },
    { n: 7, call: "ASTA_SQL_GUARD_PKG.ASSERT_SAFE_SELECT", where: "Target ADB", detail: "단일 SELECT/WITH인지 실행 직전에 다시 검사한다. DML/DDL, PL/SQL, 다중 문장, FOR UPDATE는 Source로 보내지 않는다." },
    { n: 8, call: "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE", where: "Target ADB → DB Link", detail: "GET_CONNECTION_JSON의 allowlist mapping을 사용해 원본 SQL을 Source package에 전달하고 chunk 결과를 CLOB으로 조립한다." },
    { n: 9, call: "ASTA_SOURCE_PKG.RUN_EVIDENCE_STORE_PROC", where: "Source DB", detail: "execute_source_sql=false면 ESTIMATED_PLAN으로 EXPLAIN PLAN과 객체정보만 저장하고, true면 RUN_EVIDENCE를 호출해 metrics, DBMS_XPLAN.DISPLAY_CURSOR, full count/digest를 저장한다." },
    { n: 10, call: "ASTA_VECTOR_PKG.SEARCH_SIMILAR_CASES", where: "Target ADB", detail: "positive verified 사례를 검색한다. 단계 번호는 9지만 LLM 입력이므로 실제로 후보 생성보다 먼저 호출된다." },
    { n: 11, call: "ASTA_LLM_PKG.GENERATE_SQL_ONLY_TUNING", where: "Target ADB → DBMS_CLOUD_AI.GENERATE", detail: "원본 SQL과 compact evidence로 후보를 만든다. 실행 오류 시 REPAIR_SQL_CANDIDATE를 최대 두 차례 사용할 수 있다." },
    { n: 12, call: "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE", where: "Target ADB → Source DB", detail: "미실행 모드는 후보도 ESTIMATED_PLAN으로 예상 Plan만 수집한다. 실행 opt-in이면 PLAN_ONLY 선별 후 FULL_RESULT/AUTO 재실측으로 승격한다." },
    { n: 13, call: "ASTA_PKG.BUILD_COMPARISON_JSON", where: "Target ADB", detail: "실측 모드는 optimizer intent → full-result/metadata → bind/plan → 반복 측정/noise → workload 성능 gate 순서로 verdict를 만든다. 미실행 후보는 ANALYSIS_ONLY로 성능·동등성 미검증을 명시한다." },
    { n: 14, call: "ASTA_VECTOR_PKG.SAVE_CASE", where: "Target ADB", detail: "gate-complete success와 rejected observation을 분리해 저장한다. 저장 실패가 comparison verdict를 개선으로 바꾸지 않는다." },
    { n: 15, call: "ASTA_REPORT_PKG.BUILD_REPORT", where: "Target ADB", detail: "comparison과 동일한 결론의 Markdown을 만들고 terminal progress timing을 포함하도록 다시 구성한다." },
    { n: 16, call: "ASTA_REPORT_PKG.BUILD_RESPONSE_JSON", where: "Target ADB", detail: "report와 artifact를 API JSON으로 묶어 ASTA_RUNS에 최종 status, tuned_sql, report, response를 commit한다." },
    { n: 17, call: "pollRunProgress / fetchReport", where: "Browser", detail: "GET /api/asta/runs/{run_id}/progress를 1초 간격으로 조회하고 terminal이면 GET /api/asta/runs/{run_id}/report를 한 번 가져온다." },
    { n: 18, call: "renderResult / renderReportTabs", where: "Browser", detail: "안전하게 redaction한 Markdown을 6개 탭 DOM으로 표시한다. 원문은 window.__astaLastReport.rawReport에 분리한다." },
    { n: 19, call: "downloadText", where: "Browser", detail: "보고서 다운로드를 누르면 rawReport를 로컬 Markdown 파일로 저장한다. 서버 download endpoint는 GET /api/asta/runs/{run_id}/report/download다." },
  ]);
  const ASTA_DEVELOPER_BRANCHES = Object.freeze([
    { code: "SQL_GUARD_REJECTED", result: "제출 또는 실행 직전 차단", action: "Source SQL 미실행 · 원본 SQL 유지" },
    { code: "ANALYSIS_ONLY", result: "execute_source_sql=false에서 후보와 예상 Plan 생성", action: "정상 분석 완료 · Source runtime metrics/동등성/반복 성능은 미검증" },
    { code: "NO_REWRITE", result: "안전한 구조 후보 없음", action: "7단계 SKIPPED · retain_original_sql=true" },
    { code: "CANDIDATE_FAILED / CANDIDATE_RUNTIME_LIMIT", result: "후보 Oracle 오류 또는 시간 초과", action: "repair 후에도 실패하면 원본 재실측 artifact와 실패 verdict 보존" },
    { code: "NON_EQUIVALENT", result: "result/metadata digest 불일치", action: "성능이 좋아도 후보 사용 금지 · 원본 SQL 유지" },
    { code: "INSUFFICIENT_EVIDENCE", result: "intent/full-result/bind/반복 측정 중 하나가 불완전", action: "fail-closed · 원본 SQL 유지" },
    { code: "NOT_IMPROVED", result: "동등하지만 workload 성능 기준 미달", action: "원본 SQL 유지" },
    { code: "IMPROVED", result: "모든 필수 gate 통과", action: "후보 표시; 코드 리뷰·업무 테스트·승인 전 자동 반영 없음" },
  ]);
  const ASTA_DEVELOPER_TRACE = Object.freeze([
    "화면의 Run ID와 최초 FAILED/BLOCKED 단계 code를 먼저 확보한다. SQL·bind·credential을 운영 메신저나 인계 문서에 복사하지 않는다.",
    "GET /api/asta/runs/{run_id}/progress로 ASTA_RUN_PROGRESS의 status/detail/timing을 확인하고, terminal이면 /report와 필요 시 /runs/{run_id}를 대조한다.",
    "API 서버 감사는 app/asta_audit.py가 쓰는 logs/asta/asta_request_audit.jsonl에서 run_id_prefix/hash와 endpoint event를 찾는다. 이 로그는 SQL 원문을 저장하지 않는다.",
    "ADB에서는 ASTA_RUNS, ASTA_RUN_PROGRESS, ASTA_LLM_CALL_LOG와 해당 run의 Scheduler job을 확인한다. Source 장기 작업은 ASTA_RUN_ID marker 소유 관계를 확인한 뒤에만 중단을 검토한다.",
    "정적 회귀: pytest -q tests/test_asta_manual_dialog.py tests/test_asta_developer_manual_contract.py",
    "JS/변경 검사: node --check static/js/extensions/tuning_assistant.js · node --check static/js/extensions/asta_report_tabs.js · git diff --check",
  ]);
  const PROGRESS_LOG_STATE = new WeakMap();
  const PROGRESS_RENDER_STATE = new WeakMap();
  const LLM_CALL_DETAIL_CACHE = new Map();

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
    SOURCE_OBJECT_NOT_FOUND: { title: "테이블 또는 뷰를 찾을 수 없거나 권한이 없습니다", message: "Oracle은 객체가 없을 때뿐 아니라 현재 계정에 조회 권한이 없을 때도 ORA-00942를 반환할 수 있습니다.", action: "객체명·스키마명과 ASTA 실행 계정의 직접 SELECT 권한을 DB 담당자에게 확인해 주세요." },
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
    OLTP_LATENCY_TARGET_NOT_MET: { title: "응답시간 기준을 통과하지 못했습니다", message: "과거 정책에서 개선 SQL의 응답시간 기준을 통과하지 못해 적용하지 않았습니다.", action: "현재 정책은 3초 hard guard를 사용하지 않습니다. 최신 Run으로 다시 검증해 주세요." },
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

  /** 매뉴얼 팝업의 4개 책임 영역 아키텍처를 안전한 정적 HTML로 만든다. */
  function renderArchitectureManual() {
    return `
      <div class="tuning-manual-intro">
        <p>ASTA는 사용자 요청, VM의 UI/프록시, OCI AI Lakehouse의 제어·AI 기능, ERP BaseDB의 실행 근거 수집을 분리합니다.</p>
        <div class="tuning-manual-flow" aria-label="ASTA 요청과 근거의 이동 경로">
          <span>PoC 샘플 화면</span><b aria-hidden="true">→</b><span>OCI Load Balancer → DK-AI-DEV-VM-01</span><b aria-hidden="true">→</b><span>ADB orchestration</span><b aria-hidden="true">→</b><span>Source evidence</span>
        </div>
      </div>
      <div class="tuning-manual-architecture-grid">
        ${ASTA_ARCHITECTURE_ZONES.map((zone, index) => `
          <article class="tuning-manual-zone tuning-manual-zone-${escapeHtml(zone.key)}">
            <div class="tuning-manual-zone-number" aria-hidden="true">${index + 1}</div>
            <span class="tuning-manual-eyebrow">${escapeHtml(zone.eyebrow)}</span>
            <h3>${escapeHtml(zone.title)}</h3>
            <span class="tuning-manual-compartment">${escapeHtml(zone.compartment)}</span>
            <code>${escapeHtml(zone.boundary)}</code>
            ${zone.resources.length ? `<div class="tuning-manual-zone-resources">
              <strong>OCI Resources</strong>
              <ul>${zone.resources.map((resource) => `
                <li>
                  <span>${escapeHtml(resource.type)}</span>
                  <div><b>${escapeHtml(resource.name)}</b><small>${escapeHtml(resource.detail)}</small></div>
                </li>
              `).join("")}</ul>
            </div>` : ""}
            <div class="tuning-manual-zone-functions">
              <strong>제공 기능</strong>
              <ul>${zone.functions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
            </div>
          </article>
        `).join("")}
      </div>
      <aside class="tuning-manual-principle">
        <strong>안전 경계</strong>
        <span>FastAPI는 thin proxy이고 Source SQL은 allowlisted DB Link를 통해 BaseDB package에서만 실행됩니다. ASTA는 운영 SQL이나 DB 객체를 자동 변경하지 않습니다.</span>
      </aside>`;
  }

  /** 11단계별 실행 영역, package/procedure, 상세 처리와 실패 동작을 렌더링한다. */
  function renderWorkflowManual() {
    return `
      <div class="tuning-manual-workflow-note">
        <strong>호환 단계 번호와 실제 호출 순서</strong>
        <span>화면/API 번호는 1~11을 유지하지만 실제 호출은 9 → 6 순서입니다. 현재 Vector 검색 결과는 artifact로만 보존되고 6단계 prompt에는 아직 포함되지 않습니다. 종료부는 11 저장 결과를 포함해 10 결과서를 완성합니다.</span>
      </div>
      <div class="tuning-manual-workflow-list">
        ${ASTA_WORKFLOW_GUIDE.map((step) => `
          <article class="tuning-manual-workflow-card" data-manual-step="${step.seq}">
            <div class="tuning-manual-workflow-head">
              <span class="tuning-manual-step-number">${step.seq}</span>
              <div>
                <span class="tuning-manual-step-code">${escapeHtml(step.code)}</span>
                <h3>${escapeHtml(step.title)}</h3>
              </div>
              <span class="tuning-manual-step-zone">${escapeHtml(step.zone)}</span>
            </div>
            <div class="tuning-manual-procedure">
              <span>Package / procedure</span>
              <code>${escapeHtml(step.procedure)}</code>
            </div>
            <dl class="tuning-manual-step-details">
              <div class="tuning-manual-step-task-block"><dt>상세 진행</dt><dd><ol class="tuning-manual-step-task-list">${step.tasks.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></dd></div>
              <div><dt>생성 근거</dt><dd>${escapeHtml(step.evidence)}</dd></div>
              <div><dt>실패·차단</dt><dd>${escapeHtml(step.failure)}</dd></div>
            </dl>
          </article>
        `).join("")}
      </div>`;
  }

  /** 실제 저장소 심볼을 기준으로 개발자용 end-to-end 실행·분기·추적 절차를 렌더링한다. */
  function renderDeveloperManual() {
    return `
      <section class="tuning-manual-developer-section" aria-labelledby="asta-developer-platforms-title">
        <div class="tuning-manual-developer-heading">
          <div><span class="tuning-manual-eyebrow">Code map</span><h3 id="asta-developer-platforms-title">플랫폼별 역할과 실제 코드</h3></div>
          <p>표시한 이름은 현재 Real ASTA 저장소에서 검색된 파일·함수·package입니다. 접속정보와 credential은 표시하지 않습니다.</p>
        </div>
        <div class="tuning-manual-platform-grid">
          ${ASTA_DEVELOPER_PLATFORMS.map((platform) => `
            <article class="tuning-manual-platform-card">
              <h4>${escapeHtml(platform.title)}</h4>
              <p>${escapeHtml(platform.role)}</p>
              <strong>파일</strong>
              <div class="tuning-manual-code-list">${platform.files.map((file) => `<code>${escapeHtml(file)}</code>`).join("")}</div>
              <strong>실제 심볼</strong>
              <div class="tuning-manual-symbols">${platform.symbols.map((symbol) => `<code>${escapeHtml(symbol)}</code>`).join("")}</div>
              <aside>${escapeHtml(platform.boundary)}</aside>
            </article>
          `).join("")}
        </div>
      </section>
      <section class="tuning-manual-developer-section" aria-labelledby="asta-developer-flow-title">
        <div class="tuning-manual-developer-heading">
          <div><span class="tuning-manual-eyebrow">End-to-end</span><h3 id="asta-developer-flow-title">버튼 클릭부터 보고서 다운로드까지</h3></div>
          <p>화면의 11단계 번호와 별개로, 개발자가 call stack을 따라가는 실제 호출 순서입니다.</p>
        </div>
        <ol class="tuning-manual-call-flow">
          ${ASTA_DEVELOPER_CALL_FLOW.map((item) => `
            <li>
              <span class="tuning-manual-call-number">${item.n}</span>
              <div><strong>${escapeHtml(item.call)}</strong><small>${escapeHtml(item.where)}</small><p>${escapeHtml(item.detail)}</p></div>
            </li>
          `).join("")}
        </ol>
      </section>
      <section class="tuning-manual-developer-section tuning-manual-branch-section" aria-labelledby="asta-developer-branches-title">
        <div class="tuning-manual-developer-heading">
          <div><span class="tuning-manual-eyebrow">Fail closed</span><h3 id="asta-developer-branches-title">실패·차단·원본 유지 분기</h3></div>
          <p>처리 완료와 개선 성공은 다릅니다. IMPROVED 외의 분기는 후보를 자동 반영하지 않습니다.</p>
        </div>
        <div class="tuning-manual-branch-table" role="table" aria-label="ASTA 실패와 원본 유지 분기">
          ${ASTA_DEVELOPER_BRANCHES.map((branch) => `
            <div role="row"><code role="cell">${escapeHtml(branch.code)}</code><span role="cell">${escapeHtml(branch.result)}</span><strong role="cell">${escapeHtml(branch.action)}</strong></div>
          `).join("")}
        </div>
      </section>
      <section class="tuning-manual-developer-section" aria-labelledby="asta-developer-trace-title">
        <div class="tuning-manual-developer-heading">
          <div><span class="tuning-manual-eyebrow">Operations</span><h3 id="asta-developer-trace-title">Run ID로 추적하는 방법</h3></div>
          <p>읽기 전용 조회부터 시작하고, job 중단·DB 변경·package 배포는 별도 승인 없이 수행하지 않습니다.</p>
        </div>
        <ol class="tuning-manual-trace-list">${ASTA_DEVELOPER_TRACE.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>
      </section>`;
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

  /** 진행 로그의 ISO timestamp를 로컬 시각으로 짧게 표시한다. */
  function formatProgressTimestamp(value) {
    const ms = parseTimeMs(value);
    if (ms == null) return "-";
    return new Intl.DateTimeFormat("ko-KR", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false,
    }).format(new Date(ms));
  }

  /** API 상태 코드를 사용자용 단계 상태로 변환한다. */
  function progressStatusLabel(status) {
    const normalized = String(status || "PENDING").toUpperCase();
    const labels = {
      PENDING: "대기", RUNNING: "진행 중", DONE: "완료", COMPLETED: "완료",
      SUCCESS: "완료", ACCEPTED: "완료", SKIPPED: "생략", BLOCKED: "차단",
      REJECTED: "거절", FAILED: "실패", ERROR: "오류", WARN: "주의", WARNING: "주의",
    };
    return labels[normalized] || normalized;
  }

  /** 저장된 elapsed 또는 시작/완료 시각을 이용해 단계 소요시간을 계산한다. */
  function stepElapsedMs(step, isComplete) {
    const explicit = step?.elapsed_ms ?? step?.duration_ms ?? step?.elapsedMs;
    if (explicit != null && Number.isFinite(Number(explicit))) return Math.max(0, Number(explicit));
    const start = parseTimeMs(step?.started_at || step?.at);
    if (start == null) return null;
    const status = String(step?.status || "PENDING").toUpperCase();
    const end = parseTimeMs(step?.completed_at) ?? ((status === "RUNNING" && !isComplete) ? Date.now() : null);
    return end == null ? null : Math.max(0, end - start);
  }

  /** 단계 카드에서는 sub-second와 미측정/생략을 초 단위 0.0으로 뭉개지 않는다. */
  function formatStepElapsed(step, isComplete) {
    const status = String(step?.status || "PENDING").toUpperCase();
    if (status === "SKIPPED") return "생략";
    const explicit = step?.elapsed_ms ?? step?.duration_ms ?? step?.elapsedMs;
    const elapsed = stepElapsedMs(step, isComplete);
    if (elapsed == null) {
      if (status === "PENDING") return "-";
      return "미측정";
    }
    if (elapsed === 0 && explicit == null && step?.completed_at) return "미측정";
    if (elapsed < 1000) return elapsed < 1 ? "<1ms" : `${Math.round(elapsed)}ms`;
    return formatDuration(elapsed);
  }

  /** 한 단계의 시작·현재/종료 상태를 사람이 읽을 수 있는 로그 행으로 만든다. */
  function buildStepLogs(step, isComplete) {
    const status = String(step?.status || "PENDING").toUpperCase();
    if (status === "PENDING") return ["대기 · 아직 시작하지 않은 단계입니다."];
    const started = formatProgressTimestamp(step?.started_at || step?.at);
    const completed = formatProgressTimestamp(step?.completed_at);
    const detail = redactAstaSensitiveText(step?.detail || progressStatusLabel(status));
    const logs = [`${started} · START · ${step?.label || step?.code || "단계 시작"}`];
    if (step?.completed_at) logs.push(`${completed} · ${status} · ${detail}`);
    else logs.push(`${started} · ${status} · ${detail}`);
    const elapsedText = formatStepElapsed(step, isComplete);
    if (status !== "RUNNING" && elapsedText !== "-") logs.push(`소요시간 · ${elapsedText}`);
    return logs;
  }

  /** 상세보기에서 한 단계의 상태, timing, 로그를 렌더링한다. */
  function renderProgressDetailStep(step, isComplete, llmCalls = [], runId = "") {
    const status = String(step?.status || "PENDING").toUpperCase();
    const statusClass = ["RUNNING", "DONE", "COMPLETED", "SKIPPED", "FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(status)
      ? status.toLowerCase() : "pending";
    const started = formatProgressTimestamp(step.started_at || step.at);
    const completed = formatProgressTimestamp(step.completed_at);
    const elapsedText = formatStepElapsed(step, isComplete);
    const logs = buildStepLogs(step, isComplete);
    const autoOpen = ["RUNNING", "FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(status);
    return `
      <details class="tuning-progress-detail-step tuning-progress-detail-${escapeHtml(statusClass)}" data-progress-step-card="${escapeHtml(step.seq)}" data-progress-status="${escapeHtml(status)}"${autoOpen ? " open" : ""}>
        <summary class="tuning-progress-step-head">
          <span class="tuning-progress-step-number">${escapeHtml(step.seq)}</span>
          <span class="tuning-progress-step-title">${escapeHtml(step.label)}</span>
          <span class="tuning-progress-step-elapsed" data-progress-step="${escapeHtml(step.seq)}">${escapeHtml(elapsedText)}</span>
          <span class="tuning-progress-step-status">${escapeHtml(progressStatusLabel(status))}</span>
        </summary>
        <div class="tuning-progress-step-body">
          <code class="tuning-progress-step-code">${escapeHtml(step.code)}</code>
          <dl class="tuning-progress-step-timing">
            <div><dt>시작</dt><dd class="tuning-progress-step-started">${escapeHtml(started)}</dd></div>
            <div><dt>완료</dt><dd class="tuning-progress-step-completed">${escapeHtml(completed)}</dd></div>
          </dl>
          <div class="tuning-progress-step-log-title">단계 로그</div>
          <ul class="tuning-progress-step-logs" data-progress-log-signature="${escapeHtml(logs.join("\n"))}">${logs.map((line) => `<li class="tuning-progress-step-log">${escapeHtml(line)}</li>`).join("")}</ul>
          ${String(step.code || "").toUpperCase() === "LLM_REWRITE"
            ? `<div class="tuning-llm-call-host" data-llm-call-signature="${escapeHtml(llmCallSignature(llmCalls))}">${renderLlmCallActivity(llmCalls, runId)}</div>`
            : ""}
        </div>
      </details>`;
  }

  /** 4단계의 실제 Source 작업 범위를 표시하되 확인되지 않은 세부 진척은 추정하지 않는다. */
  function renderBeforeEvidenceActivity() {
    const executeSourceSql = Boolean(document.getElementById("asta-execute-source-sql")?.checked);
    if (!executeSourceSql) {
      return `
        <section class="tuning-before-evidence-activity" aria-label="4단계 원본 SQL 예상계획 수집 상세">
          <div class="tuning-before-evidence-heading">
            <strong>4단계에서 수행 중인 작업</strong>
            <span>Source DB 미실행 안전 모드</span>
          </div>
          <ol class="tuning-before-evidence-tasks">
            <li><strong>EXPLAIN PLAN 1회</strong><span>업무 SELECT를 열거나 결과 행을 fetch하지 않고 예상 실행계획만 생성</span></li>
            <li><strong>예상 Plan 수집</strong><span>Cost, Cardinality, Access/Join operation, predicate와 optimizer note</span></li>
            <li><strong>객체 정보 수집</strong><span>PLAN_TABLE object 기준 테이블 통계와 인덱스 정의 조회</span></li>
          </ol>
          <p><strong>원본 SQL과 후보 SQL은 실행하지 않습니다.</strong> 실행시간, Buffer Gets, 결과 digest와 동등성은 미검증으로 남습니다.</p>
        </section>`;
    }
    const policy = { execution: "제한 실행 1회", executionDetail: "워밍업·반복 측정 없음", total: "최대 3회", full: true };
    return `
      <section class="tuning-before-evidence-activity" aria-label="4단계 원본 SQL 실행 정보 수집 상세">
        <div class="tuning-before-evidence-heading">
          <strong>4단계에서 수행 중인 작업</strong>
          <span>Source DB 단일 호출</span>
        </div>
        <ol class="tuning-before-evidence-tasks">
          <li><strong>${policy.execution}</strong><span>${policy.executionDetail}</span></li>
          <li><strong>실행 정보 수집</strong><span>Elapsed, Buffer Gets, Disk Reads, XPLAN, bind/child cursor, 객체 통계·인덱스</span></li>
          ${policy.full ? '<li><strong>전체 결과 건수 확인 1회</strong><span>결과 행 수와 검증 한도 확인</span></li>' : ''}
          <li><strong>${policy.full ? '전체 결과' : '제한 결과'} digest 생성 1회</strong><span>후보 SQL과 결과·컬럼 구성이 같은지 비교할 근거 생성</span></li>
        </ol>
        <p><strong>선택한 정책에서는 원본 SQL이 ${policy.total} 실행</strong>됩니다. 현재 서버는 하위 작업별 완료 신호를 보내지 않아 어느 항목이 끝났는지는 Source 응답 후 확정됩니다.</p>
      </section>`;
  }

  /** Progress 응답의 LLM 호출 요약을 안전한 표시 모델로 정규화한다. */
  function normalizeLlmCalls(progress) {
    const calls = Array.isArray(progress?.llm_calls) ? progress.llm_calls : [];
    return calls
      .map((call) => ({
        call_id: Number(call?.call_id),
        stage: String(call?.stage || "UNKNOWN").toUpperCase(),
        attempt_no: Number(call?.attempt_no || 0),
        profile_name: String(call?.profile_name || "-") ,
        call_status: String(call?.call_status || "SENT").toUpperCase(),
        prompt_chars: Number(call?.prompt_chars || 0),
        response_chars: Number(call?.response_chars || 0),
        error_code: call?.error_code == null ? null : Number(call.error_code),
        started_at: call?.started_at || null,
        completed_at: call?.completed_at || null,
        elapsed_ms: call?.elapsed_ms == null ? null : Number(call.elapsed_ms),
        detail_available: call?.detail_available !== false,
      }))
      .filter((call) => Number.isInteger(call.call_id) && call.call_id > 0);
  }

  function llmStageLabel(stage) {
    return ({
      DIAGNOSIS: "병목 진단",
      CANDIDATE_SQL: "개선 SQL 생성",
      REPAIR_SQL: "오류 SQL 복구",
    })[String(stage || "").toUpperCase()] || String(stage || "LLM 호출");
  }

  function llmCallStatusLabel(status) {
    return ({ SENT: "요청 전송", RECEIVED: "응답 완료", FAILED: "호출 실패" })[String(status || "").toUpperCase()] || String(status || "-");
  }

  /** 매초 elapsed만 바뀔 때 원문 DOM을 불필요하게 다시 만들지 않는다. */
  function llmCallSignature(calls) {
    return calls.map((call) => [
      call.call_id, call.stage, call.attempt_no, call.profile_name, call.call_status,
      call.prompt_chars, call.response_chars, call.error_code ?? "", call.completed_at || "",
    ].join("|")).join(";");
  }

  function llmCallCacheKey(runId, callId) {
    return `${runId}:${callId}`;
  }

  function renderLlmRawBlock(label, kind, text, callId) {
    if (text == null) {
      return `<div class="tuning-llm-raw-empty">${escapeHtml(label)}이 아직 없습니다.</div>`;
    }
    return `
      <details class="tuning-llm-raw-block">
        <summary>${escapeHtml(label)} <span>${Number(text.length).toLocaleString()}자</span></summary>
        <div class="tuning-llm-raw-actions"><button type="button" data-copy-llm-call="${escapeHtml(callId)}" data-copy-llm-kind="${escapeHtml(kind)}">${escapeHtml(label)} 복사</button></div>
        <pre><code>${escapeHtml(text)}</code></pre>
      </details>`;
  }

  function renderLlmCallDetail(payload) {
    const callId = Number(payload?.call_id || 0);
    const error = payload?.error_message
      ? `<div class="tuning-llm-call-error"><strong>호출 오류</strong><code>${escapeHtml(payload.error_message)}</code></div>`
      : "";
    return `
      <div class="tuning-llm-sensitive-note">운영 SQL과 XPLAN이 포함될 수 있습니다. 필요한 경우에만 아래 원문을 여세요.</div>
      ${error}
      ${renderLlmRawBlock("LLM Prompt", "prompt", payload?.prompt, callId)}
      ${renderLlmRawBlock("Provider 응답", "response", payload?.response, callId)}`;
  }

  function renderLlmCallActivity(calls, runId) {
    if (!calls.length) {
      return `<section class="tuning-llm-call-activity"><div class="tuning-llm-call-heading"><strong>LLM 요청·응답</strong><span>대기</span></div><p>LLM 호출이 시작되면 단계, profile, 요청·응답 상태가 여기에 표시됩니다.</p></section>`;
    }
    const rows = calls.map((call) => {
      const cacheKey = llmCallCacheKey(runId, call.call_id);
      const cachedValue = LLM_CALL_DETAIL_CACHE.get(cacheKey);
      const cached = cachedValue
        && String(cachedValue.call_status || "").toUpperCase() === call.call_status
        && Number(cachedValue.response_chars || 0) === call.response_chars
        ? cachedValue
        : null;
      if (cachedValue && !cached) LLM_CALL_DETAIL_CACHE.delete(cacheKey);
      const elapsed = call.elapsed_ms == null ? "미측정" : formatDuration(call.elapsed_ms);
      const statusClass = ["SENT", "RECEIVED", "FAILED"].includes(call.call_status) ? call.call_status.toLowerCase() : "sent";
      return `
        <article class="tuning-llm-call-card tuning-llm-call-${escapeHtml(statusClass)}" data-llm-call-id="${escapeHtml(call.call_id)}">
          <div class="tuning-llm-call-summary">
            <strong>${escapeHtml(llmStageLabel(call.stage))}</strong>
            <span>${escapeHtml(call.attempt_no)}차</span>
            <em>${escapeHtml(llmCallStatusLabel(call.call_status))}</em>
          </div>
          <dl>
            <div><dt>Profile</dt><dd>${escapeHtml(call.profile_name)}</dd></div>
            <div><dt>소요시간</dt><dd data-llm-call-elapsed="${escapeHtml(call.call_id)}">${escapeHtml(elapsed)}</dd></div>
            <div><dt>Prompt</dt><dd>${escapeHtml(call.prompt_chars.toLocaleString())}자</dd></div>
            <div><dt>응답</dt><dd>${escapeHtml(call.response_chars.toLocaleString())}자</dd></div>
          </dl>
          ${call.error_code == null ? "" : `<div class="tuning-llm-call-code">오류 코드 ${escapeHtml(call.error_code)}</div>`}
          <button class="tuning-llm-call-load" type="button" data-load-llm-call="${escapeHtml(call.call_id)}"${call.detail_available ? "" : " disabled"}>${cached ? "원문 새로고침" : "Prompt·응답 원문 보기"}</button>
          <div class="tuning-llm-call-detail" data-llm-call-detail="${escapeHtml(call.call_id)}">${cached ? renderLlmCallDetail(cached) : ""}</div>
        </article>`;
    }).join("");
    return `
      <section class="tuning-llm-call-activity" aria-label="6단계 LLM 요청과 응답 상세">
        <div class="tuning-llm-call-heading"><strong>LLM 요청·응답</strong><span>${escapeHtml(calls.length)}회</span></div>
        <p>목록은 progress에서 실시간 조회합니다. 원문은 버튼을 누를 때만 별도 API로 불러옵니다.</p>
        <div class="tuning-llm-call-list">${rows}</div>
      </section>`;
  }

  function attachLlmCallActivityHandlers(target, runId) {
    target.querySelectorAll("[data-load-llm-call]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", async () => {
        const callId = Number(button.dataset.loadLlmCall);
        const detail = target.querySelector(`[data-llm-call-detail="${callId}"]`);
        if (!detail || !Number.isInteger(callId) || callId < 1 || !runId) return;
        const baseUrl = String(window.__astaRunLookupBaseUrl || DEFAULT_ORDS_BASE_URL).replace(/\/+$/, "");
        button.disabled = true;
        button.textContent = "원문 불러오는 중";
        try {
          const payload = await fetchJson(`${baseUrl}/runs/${encodeURIComponent(runId)}/llm-calls/${callId}`);
          LLM_CALL_DETAIL_CACHE.set(llmCallCacheKey(runId, callId), payload);
          detail.innerHTML = renderLlmCallDetail(payload);
          attachLlmCallActivityHandlers(target, runId);
          button.textContent = "원문 새로고침";
        } catch (error) {
          detail.innerHTML = `<div class="tuning-llm-call-error">원문을 불러오지 못했습니다: ${escapeHtml(error?.message || error)}</div>`;
          button.textContent = "다시 시도";
        } finally {
          button.disabled = false;
        }
      });
    });
    target.querySelectorAll("[data-copy-llm-call]").forEach((button) => {
      if (button.dataset.bound === "true") return;
      button.dataset.bound = "true";
      button.addEventListener("click", async () => {
        const callId = Number(button.dataset.copyLlmCall);
        const payload = LLM_CALL_DETAIL_CACHE.get(llmCallCacheKey(runId, callId));
        const value = button.dataset.copyLlmKind === "response" ? payload?.response : payload?.prompt;
        try {
          await copyPlainText(value || "");
          window.Toast?.show?.("LLM 원문을 복사했습니다.", "success");
        } catch (_) {
          window.Toast?.show?.("LLM 원문 복사에 실패했습니다.", "error");
        }
      });
    });
  }

  function refreshLlmCallActivity(target, calls, runId) {
    const host = target.querySelector(".tuning-llm-call-host");
    if (!host) return;
    const signature = llmCallSignature(calls);
    if (host.dataset.llmCallSignature !== signature) {
      host.dataset.llmCallSignature = signature;
      host.innerHTML = renderLlmCallActivity(calls, runId);
    }
    calls.forEach((call) => {
      const elapsed = host.querySelector(`[data-llm-call-elapsed="${call.call_id}"]`);
      if (elapsed) elapsed.textContent = call.elapsed_ms == null ? "미측정" : formatDuration(call.elapsed_ms);
    });
    attachLlmCallActivityHandlers(target, runId);
  }

  /** 단계 상태가 실제로 바뀔 때만 개발자 콘솔에 구조화 로그를 남긴다. */
  function logChangedProgressSteps(target, runId, steps) {
    if (!runId) return;
    const previous = PROGRESS_LOG_STATE.get(target);
    const state = previous?.runId === runId ? previous.signatures : new Map();
    const next = new Map();
    steps.forEach((step) => {
      const status = String(step.status || "PENDING").toUpperCase();
      const signature = [status, step.started_at || step.at || "", step.completed_at || "", step.elapsed_ms ?? "", step.detail || ""].join("|");
      next.set(step.code, signature);
      if (status !== "PENDING" && state.get(step.code) !== signature) {
        console.info("asta-stage-progress", {
          run_id: runId, seq: step.seq, code: step.code, label: step.label, status,
          started_at: step.started_at || step.at || null,
          completed_at: step.completed_at || null,
          elapsed_ms: step.elapsed_ms ?? null,
          detail: redactAstaSensitiveText(step.detail || ""),
        });
      }
    });
    PROGRESS_LOG_STATE.set(target, { runId, signatures: next });
  }

  /** 같은 Run의 DOM 골격을 유지한 채 현재 단계와 각 카드만 부분 갱신한다. */
  function refreshProgressView(target, steps, options) {
    const { isComplete, detail, totalElapsedText, label, compactLabel, dotClass, isRunning, isFailed, beforeEvidenceRunning, llmCalls, runId } = options;
    const running = steps.find((step) => String(step.status || "").toUpperCase() === "RUNNING");
    const failed = steps.find((step) => ["FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(String(step.status || "").toUpperCase()));
    const done = steps.filter((step) => ["DONE", "COMPLETED"].includes(String(step.status || "").toUpperCase()));
    const current = isComplete ? null : running || failed || done[done.length - 1] || steps[0];
    const currentElapsed = current ? stepElapsedMs(current, isComplete) : null;
    const currentElapsedText = current ? formatStepElapsed(current, isComplete) : "";
    const currentProgress = target.querySelector(".tuning-current-progress");
    if (currentProgress) currentProgress.className = `tuning-current-progress tuning-current-${dotClass}`;
    const dot = target.querySelector(".tuning-current-dot");
    if (dot) {
      if (isRunning) {
        if (!dot.querySelector(".tuning-spinner")) dot.innerHTML = '<span class="tuning-spinner"></span>';
      } else {
        dot.textContent = isComplete ? "✓" : isFailed ? "!" : "";
      }
    }
    const main = target.querySelector(".tuning-current-main");
    if (main) main.textContent = label;
    const stepElement = target.querySelector(".tuning-current-step");
    if (stepElement) stepElement.textContent = compactLabel;
    const detailElement = target.querySelector(".tuning-current-detail");
    if (detailElement) {
      const showDetail = (isFailed || beforeEvidenceRunning) && Boolean(detail);
      detailElement.textContent = showDetail ? detail : "";
      detailElement.hidden = !showDetail;
    }
    const activity = target.querySelector(".tuning-before-evidence-host");
    if (activity) activity.hidden = !beforeEvidenceRunning;
    const elapsedElement = target.querySelector(".tuning-current-elapsed");
    if (elapsedElement) {
      elapsedElement.textContent = currentElapsedText;
      elapsedElement.hidden = currentElapsed == null;
    }
    target.querySelectorAll(".tuning-current-total, .tuning-progress-drawer-current strong").forEach((element) => {
      element.textContent = totalElapsedText;
      element.hidden = !totalElapsedText;
    });
    const drawerCurrent = target.querySelector(".tuning-progress-drawer-current span");
    if (drawerCurrent) drawerCurrent.textContent = label;
    steps.forEach((step) => {
      const card = Array.from(target.querySelectorAll("[data-progress-step-card]"))
        .find((item) => item.getAttribute("data-progress-step-card") === String(step.seq));
      if (!card) return;
      const status = String(step.status || "PENDING").toUpperCase();
      const statusClass = ["RUNNING", "DONE", "COMPLETED", "SKIPPED", "FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(status)
        ? status.toLowerCase() : "pending";
      const previousStatus = card.getAttribute("data-progress-status") || "PENDING";
      card.className = `tuning-progress-detail-step tuning-progress-detail-${statusClass}`;
      card.setAttribute("data-progress-status", status);
      if (previousStatus !== status) {
        card.open = ["RUNNING", "FAILED", "ERROR", "BLOCKED", "REJECTED"].includes(status);
      }
      const statusElement = card.querySelector(".tuning-progress-step-status");
      if (statusElement) statusElement.textContent = progressStatusLabel(status);
      const startedElement = card.querySelector(".tuning-progress-step-started");
      if (startedElement) startedElement.textContent = formatProgressTimestamp(step.started_at || step.at);
      const completedElement = card.querySelector(".tuning-progress-step-completed");
      if (completedElement) completedElement.textContent = formatProgressTimestamp(step.completed_at);
      const elapsedElement = card.querySelector(".tuning-progress-step-elapsed");
      if (elapsedElement) elapsedElement.textContent = formatStepElapsed(step, isComplete);
      const logs = buildStepLogs(step, isComplete);
      const logsElement = card.querySelector(".tuning-progress-step-logs");
      const logSignature = logs.join("\n");
      if (logsElement && logsElement.getAttribute("data-progress-log-signature") !== logSignature) {
        logsElement.setAttribute("data-progress-log-signature", logSignature);
        logsElement.innerHTML = logs.map((line) => `<li class="tuning-progress-step-log">${escapeHtml(line)}</li>`).join("");
      }
    });
    refreshLlmCallActivity(target, llmCalls, runId);
  }

  /**
   * ISO 시간 문자열을 밀리초 timestamp로 파싱한다.
   */
  function normalizeAstaTimestamp(value) {
    const raw = String(value || "").trim();
    if (!raw) return raw;
    // Timezone-less Oracle timestamps are UTC. Browsers otherwise interpret
    // them as local time, which adds 540 minutes in Asia/Seoul.
    const match = raw.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.(\d+))?$/);
    if (!match) return raw;
    const fraction = match[3] ? `.${match[3].padEnd(3, "0").slice(0, 3)}` : "";
    return `${match[1]}T${match[2]}${fraction}Z`;
  }

  function parseTimeMs(value) {
    if (!value) return null;
    const ms = new Date(normalizeAstaTimestamp(value)).getTime();
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

  /** 감싸진 ORA-200xx보다 실제 SQL 실행 원인인 ORA 오류를 우선 추출한다. */
  function extractAstaOracleError(value) {
    const text = String(value || "");
    const matches = text.match(/ORA-\d{5}:\s*.*?(?=\s+ORA-\d{5}:|[\r\n]|$)/gi) || [];
    if (!matches.length) return "";
    const cleaned = matches.map((item) => item.trim());
    return cleaned.find((item) => {
      const code = Number(item.slice(4, 9));
      return code < 20000 || code > 20999;
    }) || cleaned[cleaned.length - 1];
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
    const oracleError = extractAstaOracleError(`${technicalMessage}\n${combined}`);
    return known
      ? { code, ...known, technicalMessage, oracleError }
      : {
          code: String(value?.error_code || value?.error?.code || value?.workflow_state?.reason_code || "ASTA_ANALYSIS_INCOMPLETE"),
          title: "분석을 완료하지 못했습니다",
          message: "안전을 위해 개선 SQL을 적용하지 않았으며 원본 SQL은 변경되지 않았습니다.",
          action: "잠시 후 다시 시도하고, 같은 문제가 계속되면 Run ID와 문의 코드를 담당자에게 전달해 주세요.",
          technicalMessage,
          oracleError,
        };
  }

  function isTruthyFlag(value) {
    if (typeof value === "boolean") return value;
    if (value == null) return false;
    return ["true", "1", "y", "yes"].includes(String(value).trim().toLowerCase());
  }

  function isEstimatedPlanAnalysisOnly(data) {
    const comparison = data?.comparison || data?.artifacts?.comparison || {};
    const runtimeEvidence = data?.runtime_evidence || data?.artifacts?.source_evidence || {};
    const verdict = String(comparison?.verdict || data?.verdict || "").toUpperCase();
    const reason = String(comparison?.verdict_reason || data?.verdict_reason || "").toUpperCase();
    const analysisMode = String(data?.analysis_mode || comparison?.analysis_mode || "").toUpperCase();
    const screenMode = String(comparison?.screen_mode || "").toUpperCase();
    const planKind = String(runtimeEvidence?.plan_kind || "").toUpperCase();
    const sourceExecuted = data?.source_sql_executed ?? comparison?.source_sql_executed ?? runtimeEvidence?.source_sql_executed;
    return verdict === "ANALYSIS_ONLY"
      || analysisMode === "ESTIMATED_PLAN_ONLY"
      || reason === "ESTIMATED_PLAN_ONLY_RUNTIME_NOT_EXECUTED"
      || (screenMode === "ESTIMATED_PLAN" && !isTruthyFlag(sourceExecuted))
      || (planKind === "ESTIMATED" && !isTruthyFlag(sourceExecuted));
  }

  function renderAnalysisModeBadge(data) {
    if (isEstimatedPlanAnalysisOnly(data)) {
      return '<span class="tuning-report-mode-badge tuning-report-mode-analysis">미실행 분석 모드 · 성능·동등성 미검증</span>';
    }
    if (isTruthyFlag(data?.source_sql_executed || data?.comparison?.source_sql_executed || data?.runtime_evidence?.source_sql_executed)) {
      return '<span class="tuning-report-mode-badge tuning-report-mode-runtime">Source 실측 검증 모드</span>';
    }
    return '<span class="tuning-report-mode-badge tuning-report-mode-unknown">분석 모드 확인 중</span>';
  }

  /** 서버 상태머신과 deterministic comparison을 하나의 terminal outcome으로 해석한다. */
  function astaWorkflowOutcome(data) {
    const workflowStatus = String(data?.workflow_state?.overall_status || data?.state_machine?.overall_status || "").toUpperCase();
    const responseStatus = String(data?.status || "").toUpperCase();
    const verdict = String(data?.comparison?.verdict || data?.verdict || "").toUpperCase();
    const failures = ["BLOCKED", "REJECTED", "FAILED", "ERROR"];
    if (failures.includes(workflowStatus)) return workflowStatus;
    if (failures.includes(responseStatus)) return responseStatus;
    if (isEstimatedPlanAnalysisOnly(data) || verdict === "ANALYSIS_ONLY") return "ACCEPTED";
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
  function collapseInputSectionForResult() {
    const inputSection = document.getElementById("asta-input-section");
    if (inputSection) inputSection.open = false;
  }

  function renderResult(target, data) {
    const report = data?.detailed_report_markdown || data?.report_markdown || data?.llm_final_report?.report_markdown || data?.report || data?.message || "구조화된 Gate 결과만 제공되었습니다.";
    const safeReport = redactAstaReportForUi(report);
    const runId = data?.run_id ? `<span class="muted tuning-report-run-id">Run ID: ${escapeHtml(data.run_id)}</span>` : "";
    const modeBadge = renderAnalysisModeBadge(data);
    const analysisNotice = isEstimatedPlanAnalysisOnly(data)
      ? `<div class="tuning-analysis-mode-notice" role="status"><strong>미실행 분석 모드</strong><span>원본·후보 SQL을 Source DB에서 실행하지 않았습니다. 후보 SQL과 예상 Plan은 분석 결과로 표시하지만 성능·동등성 미검증 상태입니다.</span></div>`
      : "";
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
    collapseInputSectionForResult();
    target.innerHTML = `
      <details class="card tuning-report-card tuning-collapsible-section" open>
        <summary class="tuning-report-collapse-summary">
          <span class="section-title">ASTA 분석 결과</span>
          ${runId}
          ${modeBadge}
        </summary>
        <div class="tuning-report-collapse-body">
        <div class="tuning-report-header">
          <div class="tuning-report-head">
            <div class="tuning-report-actions" aria-label="결과서 작업">
            </div>
          </div>
          <div class="tuning-report-status-slot"></div>
          <div id="asta-report-tabs-host" class="tuning-report-tabs-host"></div>
        </div>
        ${analysisNotice}
        ${oraBanner}
        <div id="asta-report-scroll" class="code-block tuning-report-scroll" tabindex="0"></div>
        </div>
      </details>`;
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
    if (reportActions && downloadButton) reportActions.append(downloadButton);
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
      issue.oracleError ? `Oracle 오류: ${issue.oracleError}` : "",
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
        ${issue.oracleError ? `<div style="padding:10px 12px; border:1px solid #fca5a5; border-radius:8px; background:#fff;"><strong style="color:#991b1b;">Oracle 오류</strong><br><code style="display:inline-block; margin-top:6px; color:#991b1b; font-weight:800;">${escapeHtml(issue.oracleError)}</code></div>` : ""}
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
    const byIndex = DEFAULT_STEPS.map((step) => ({
      ...step, status: "PENDING", detail: "대기", at: "",
      started_at: null, completed_at: null, elapsed_ms: null,
    }));
    incoming.forEach((rawStep, rawIndex) => {
      const mappedIndex = progressStageIndex(rawStep);
      const index = mappedIndex == null ? Math.min(rawIndex, DEFAULT_STEPS.length - 1) : mappedIndex;
      const base = DEFAULT_STEPS[index];
      byIndex[index] = {
        ...base,
        status: rawStep.status || byIndex[index].status || "PENDING",
        detail: rawStep.detail || rawStep.message || rawStep.label || byIndex[index].detail || "",
        at: rawStep.at || rawStep.started_at || rawStep.created_at || rawStep.updated_at || rawStep.completed_at || byIndex[index].at || "",
        started_at: rawStep.started_at || rawStep.created_at || byIndex[index].started_at || null,
        completed_at: rawStep.completed_at || rawStep.ended_at || byIndex[index].completed_at || null,
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

  /** 현재 진행 요약과 분리된 11단계 상세 Drawer를 연다. */
  function openProgressDrawer(target, focusClose = true) {
    const drawer = target.querySelector(".tuning-progress-drawer");
    if (!drawer) return;
    drawer.hidden = false;
    if (focusClose) drawer.querySelector(".tuning-progress-drawer-close")?.focus({ preventScroll: true });
  }

  /** 진행 상세 Drawer를 닫고 compact 현재 단계 요약으로 돌아간다. */
  function closeProgressDrawer(target) {
    const drawer = target.querySelector(".tuning-progress-drawer");
    if (!drawer) return;
    drawer.hidden = true;
    target.querySelector(".tuning-progress-open")?.focus({ preventScroll: true });
  }

  /**
   * ASTA 진행률 스택과 상태 배지를 화면에 그린다.
   */
  function renderProgressStack(target, progress) {
    const drawerWasOpen = !target.querySelector(".tuning-progress-drawer")?.hidden;
    const drawerScrollTop = target.querySelector(".tuning-progress-drawer-body")?.scrollTop || 0;
    const steps = normalizeSteps(progress);
    const llmCalls = normalizeLlmCalls(progress);
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
    if (ready) {
      target.hidden = true;
      target.innerHTML = "";
      PROGRESS_LOG_STATE.delete(target);
      PROGRESS_RENDER_STATE.delete(target);
      return;
    }
    target.hidden = false;
    const currentElapsedMs = !isOverallComplete && current ? stepElapsedMs(current, isComplete) : null;
    const beforeEvidenceRunning = String(current?.code || "").toUpperCase() === "BEFORE_EVIDENCE" && isRunning;
    let observationDetail = "";
    if (beforeEvidenceRunning) {
      observationDetail = "원본 SQL 최대 3회 실행 및 실행계획·결과 검증 중";
    }
    const totalElapsed = totalElapsedMs(progress, steps, isComplete);
    const totalElapsedText = !ready && totalElapsed != null ? `전체 ${formatDuration(totalElapsed)}` : "";
    const progressIssue = isFailed ? friendlyAstaIssue(progress, current?.detail || statusText) : null;
    const label = ready ? "대기 중" : isComplete ? "완료" : isFailed ? "확인 필요" : current?.label || statusText;
    const detail = isComplete ? "AI 분석이 종료되었습니다" : ready ? "SQL 입력 후 AI 분석 실행을 누르세요" : isFailed ? progressIssue.message : observationDetail || current?.detail || statusText;
    const currentPosition = current ? Math.max(1, steps.indexOf(current) + 1) : steps.length;
    const compactLabel = `${currentPosition}/${steps.length}`;
    const dotClass = isFailed ? "failed" : isComplete ? "done" : isRunning ? "running" : "pending";
    logChangedProgressSteps(target, runId, steps);
    const previousRender = PROGRESS_RENDER_STATE.get(target);
    if (previousRender?.runId === runId && target.querySelector(".tuning-current-progress")) {
      refreshProgressView(target, steps, {
        isComplete, detail, totalElapsedText, label, compactLabel, dotClass, isRunning, isFailed, beforeEvidenceRunning, llmCalls, runId,
      });
      return;
    }
    target.innerHTML = `
      <div class="tuning-current-progress tuning-current-${escapeHtml(dotClass)}" title="${escapeHtml(detail || "현재 진행 단계와 전체 수행 시간을 표시합니다")}">
        <span class="tuning-current-dot" aria-hidden="true">${isRunning ? '<span class="tuning-spinner"></span>' : isComplete ? '✓' : isFailed ? '!' : ''}</span>
        <span class="tuning-current-step">${escapeHtml(compactLabel)}</span>
        <span class="tuning-current-main">${escapeHtml(label)}</span>
        <span class="tuning-current-detail"${(isFailed || beforeEvidenceRunning) && detail ? "" : " hidden"}>${escapeHtml((isFailed || beforeEvidenceRunning) ? detail : "")}</span>
        <span class="tuning-current-elapsed"${currentElapsedMs == null ? " hidden" : ""}>${escapeHtml(current ? formatStepElapsed(current, isComplete) : "")}</span>
        <span class="tuning-current-total"${totalElapsedText ? "" : " hidden"}>${escapeHtml(totalElapsedText)}</span>
        <button class="tuning-progress-open" type="button" aria-haspopup="dialog">상세</button>
      </div>
      <div class="tuning-progress-drawer" hidden>
        <section class="tuning-progress-drawer-panel" role="dialog" aria-modal="true" aria-label="ASTA 11단계 전체 진행상태와 로그" tabindex="-1">
          <header class="tuning-progress-drawer-header">
            <div>
              <span class="tuning-progress-drawer-eyebrow">ASTA RUN PROGRESS</span>
              <h3>분석 진행상태</h3>
              ${runId ? `<div class="tuning-progress-drawer-run"><code title="ASTA Run ID">${escapeHtml(runId)}</code><button class="tuning-copy-run-id" type="button" title="Run ID 값만 복사">복사</button></div>` : ""}
            </div>
            <button class="tuning-progress-drawer-close" type="button" aria-label="진행 상세 닫기">닫기</button>
          </header>
          <div class="tuning-progress-drawer-body">
            <div class="tuning-progress-drawer-current">
              <span>${escapeHtml(label)}</span>
              <strong${totalElapsedText ? "" : " hidden"}>${escapeHtml(totalElapsedText)}</strong>
            </div>
            <div class="tuning-before-evidence-host"${beforeEvidenceRunning ? "" : " hidden"}>${renderBeforeEvidenceActivity()}</div>
            <div class="tuning-progress-step-list">
              ${steps.map((step) => renderProgressDetailStep(step, isComplete, llmCalls, runId)).join("")}
            </div>
          </div>
        </section>
      </div>`;
    PROGRESS_RENDER_STATE.set(target, { runId });
    const drawer = target.querySelector(".tuning-progress-drawer");
    target.querySelector(".tuning-progress-open")?.addEventListener("click", () => openProgressDrawer(target));
    target.querySelector(".tuning-progress-drawer-close")?.addEventListener("click", () => closeProgressDrawer(target));
    drawer?.addEventListener("click", (event) => {
      if (event.target === drawer) closeProgressDrawer(target);
    });
    drawer?.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeProgressDrawer(target);
    });
    if (drawerWasOpen) {
      openProgressDrawer(target, false);
      const drawerBody = target.querySelector(".tuning-progress-drawer-body");
      if (drawerBody) drawerBody.scrollTop = drawerScrollTop;
    }
    target.querySelector(".tuning-copy-run-id")?.addEventListener("click", async () => {
      try {
        await copyPlainText(runId);
        window.Toast?.show?.("Run ID만 복사했습니다.", "success");
      } catch (_) {
        window.Toast?.show?.("Run ID 복사에 실패했습니다.", "error");
      }
    });
    attachLlmCallActivityHandlers(target, runId);
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
    window.__astaRunLookupBaseUrl = baseUrl;
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
          --tuning-panel: var(--surface);
          --tuning-surface: var(--surface-alt);
          --tuning-border: var(--border);
          --tuning-text: var(--text);
          --tuning-muted: var(--text-muted);
          --tuning-accent: var(--primary);
          min-height: calc(100vh - 86px);
          margin: calc(var(--space-5) * -1);
          padding: clamp(18px, 2.4vw, 34px);
          color: var(--tuning-text);
          background:
            radial-gradient(circle at 12% 0%, rgba(199,70,52,.10), transparent 30%),
            radial-gradient(circle at 88% 8%, rgba(180,83,9,.06), transparent 28%),
            linear-gradient(135deg, var(--surface-alt) 0%, var(--surface) 48%, #fbf4f2 100%);
        }
        .tuning-hero {
          display:flex; align-items:flex-end; justify-content:space-between; gap:18px;
          margin-bottom:18px;
        }
        .tuning-kicker {
          display:inline-flex; align-items:center; gap:8px; margin-bottom:10px;
          color:var(--text-muted); font-size:12px; letter-spacing:.08em; text-transform:uppercase;
        }
        .tuning-dot { width:8px; height:8px; border-radius:999px; background:var(--tuning-accent); box-shadow:0 0 0 4px var(--primary-light); }
        .tuning-title { margin:0; font-size:clamp(30px, 4vw, 48px); line-height:1; letter-spacing:-1.05px; font-weight:590; }
        .tuning-secret-trigger { appearance:none; border:0; padding:0; margin:0; color:inherit; background:transparent; font:inherit; letter-spacing:inherit; line-height:inherit; cursor:default; }
        .tuning-secret-trigger:focus-visible { outline:2px solid var(--primary); outline-offset:3px; border-radius:3px; }
        .tuning-subtitle { margin:12px 0 0; color:var(--tuning-muted); max-width:780px; line-height:1.6; }
        .tuning-grid { display:block; }
        .tuning-card, .tuning-report-card {
          border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface); box-shadow:none;
        }
        .tuning-card { padding:0; overflow:hidden; }
        .tuning-card-title { justify-content:space-between; margin:0; color:var(--text); font-weight:590; }
        .tuning-collapsible-body { padding:var(--space-4); border-top:1px solid var(--border); }
        .tuning-collapsible-summary, .tuning-report-collapse-summary {
          display:flex; align-items:center; gap:var(--space-2); min-height:52px; padding:var(--space-4);
          cursor:pointer; list-style:none; user-select:none; background:var(--surface); color:var(--text);
        }
        .tuning-collapsible-summary::-webkit-details-marker,
        .tuning-report-collapse-summary::-webkit-details-marker { display:none; }
        .tuning-collapsible-summary::after,
        .tuning-report-collapse-summary::after {
          content:'›'; flex:0 0 auto; color:var(--tuning-muted, var(--text-muted)); font-size:20px; line-height:1;
          transform:rotate(0deg); transition:transform .15s ease;
        }
        .tuning-collapsible-section[open] > .tuning-collapsible-summary::after,
        .tuning-collapsible-section[open] > .tuning-report-collapse-summary::after { transform:rotate(90deg); }
        .tuning-collapsible-summary:focus-visible,
        .tuning-report-collapse-summary:focus-visible { outline:2px solid var(--tuning-accent, var(--primary)); outline-offset:3px; border-radius:8px; }
        .tuning-hero-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
        .tuning-top-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
        body.tuning-manual-open { overflow:hidden; }
        .tuning-manual-dialog[hidden] { display:none; }
        .tuning-manual-dialog { position:fixed; inset:0; z-index:2600; display:grid; place-items:center; padding:24px; background:rgba(15,23,42,.48); backdrop-filter:blur(3px); }
        .tuning-manual-panel { width:min(1180px, 96vw); max-height:min(92dvh, 980px); display:flex; flex-direction:column; overflow:hidden; border:1px solid var(--border); border-radius:18px; background:var(--surface); color:var(--text); box-shadow:0 28px 80px rgba(15,23,42,.28); }
        .tuning-manual-header { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding:20px 22px 16px; border-bottom:1px solid var(--border); background:var(--surface); }
        .tuning-manual-header > div { min-width:0; }
        .tuning-manual-header .tuning-manual-eyebrow { display:block; margin-bottom:5px; }
        .tuning-manual-header h2 { margin:0; font-size:clamp(20px, 2.5vw, 30px); letter-spacing:-.02em; }
        .tuning-manual-header p { margin:7px 0 0; color:var(--text-muted); font-size:13px; line-height:1.5; }
        .tuning-manual-close { flex:0 0 auto; min-width:42px; min-height:38px; padding:8px 11px; border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface); color:var(--text); font-weight:750; cursor:pointer; }
        .tuning-manual-close:hover { border-color:var(--border-strong); background:var(--surface-hover); }
        .tuning-manual-close:focus-visible, .tuning-manual-tab:focus-visible { outline:2px solid var(--primary); outline-offset:2px; }
        .tuning-manual-tabs { display:grid; grid-template-columns:repeat(3,minmax(190px,260px)); gap:10px; padding:12px 22px; border-bottom:1px solid var(--border); background:var(--surface-alt); }
        .tuning-manual-tab { position:relative; display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:9px; min-height:50px; padding:8px 12px; border:1px solid var(--border-strong); border-radius:var(--radius-lg); background:var(--surface); color:var(--text); font-size:13px; font-weight:750; text-align:left; cursor:pointer; box-shadow:var(--shadow-sm); transition:transform .15s ease,border-color .15s ease,box-shadow .15s ease,background .15s ease; }
        .tuning-manual-tab::after { content:'열기'; padding:3px 6px; border-radius:999px; background:var(--surface-alt); color:var(--text-muted); font-size:9px; font-weight:800; }
        .tuning-manual-tab:hover { border-color:var(--primary); color:var(--primary); background:var(--primary-light); box-shadow:var(--shadow-md); transform:translateY(-1px); }
        .tuning-manual-tab[aria-selected="true"] { border-color:var(--primary); background:var(--surface); color:var(--primary); box-shadow:inset 0 -3px var(--primary),var(--shadow-sm); }
        .tuning-manual-tab[aria-selected="true"]::after { content:'선택됨 ✓'; background:var(--primary); color:#fff; }
        .tuning-manual-tab-index { display:grid; place-items:center; width:28px; height:28px; border-radius:8px; background:var(--surface-alt); color:var(--text-muted); font-size:10px; font-weight:850; }
        .tuning-manual-tab[aria-selected="true"] .tuning-manual-tab-index { background:var(--primary-light); color:var(--primary); }
        .tuning-manual-tab-label { min-width:0; }
        .tuning-manual-content { flex:1 1 auto; min-height:0; overflow:auto; padding:22px; background:var(--surface-alt); }
        .tuning-manual-panel-view[hidden] { display:none; }
        .tuning-manual-intro { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:16px; }
        .tuning-manual-intro p { max-width:680px; margin:0; color:var(--text-muted); line-height:1.6; }
        .tuning-manual-flow { display:flex; align-items:center; gap:7px; flex-wrap:wrap; justify-content:flex-end; color:var(--text-muted); font-size:11px; }
        .tuning-manual-flow span { padding:5px 8px; border:1px solid var(--border); border-radius:999px; background:var(--surface); }
        .tuning-manual-flow b { color:var(--primary); }
        .tuning-manual-architecture-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
        .tuning-manual-zone { position:relative; min-width:0; padding:16px; border:1px solid var(--border); border-top:4px solid var(--primary); border-radius:var(--radius-lg); background:var(--surface); }
        .tuning-manual-zone::after { content:'→'; position:absolute; top:50%; right:-12px; z-index:1; display:grid; place-items:center; width:12px; color:var(--primary); font-size:16px; font-weight:800; transform:translateY(-50%); }
        .tuning-manual-zone:last-child::after { display:none; }
        .tuning-manual-zone-user { border-top-color:#64748b; }
        .tuning-manual-zone-ui { border-top-color:#2563eb; }
        .tuning-manual-zone-lakehouse { border-top-color:#7c3aed; }
        .tuning-manual-zone-basedb { border-top-color:#059669; }
        .tuning-manual-zone-number { display:grid; place-items:center; width:26px; height:26px; margin-bottom:12px; border-radius:8px; background:var(--surface-alt); color:var(--primary); font-size:12px; font-weight:850; }
        .tuning-manual-eyebrow { color:var(--text-muted); font-size:10px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
        .tuning-manual-zone h3 { margin:5px 0 7px; font-size:17px; line-height:1.35; }
        .tuning-manual-compartment { display:inline-flex; max-width:100%; margin-bottom:8px; padding:4px 7px; border-radius:999px; background:var(--primary-light); color:var(--primary); font-size:9px; font-weight:800; line-height:1.35; }
        .tuning-manual-zone code { display:block; min-height:42px; padding:7px 8px; border:1px solid var(--border); border-radius:8px; background:var(--surface-alt); color:var(--primary); font-size:10px; line-height:1.35; overflow-wrap:anywhere; }
        .tuning-manual-zone-resources { margin-top:11px; padding-top:10px; border-top:1px solid var(--border); }
        .tuning-manual-zone-resources > strong, .tuning-manual-zone-functions > strong { display:block; color:var(--text); font-size:10px; letter-spacing:.03em; }
        .tuning-manual-zone-resources ul { display:grid; gap:5px; margin:7px 0 0; padding:0; list-style:none; }
        .tuning-manual-zone-resources li { display:grid; grid-template-columns:64px minmax(0,1fr); gap:6px; align-items:start; padding:6px; border:1px solid var(--border); border-radius:8px; background:var(--surface-alt); }
        .tuning-manual-zone-resources li > span { display:inline-flex; justify-content:center; padding:2px 4px; border-radius:999px; background:var(--surface); color:var(--primary); font-size:8px; font-weight:800; }
        .tuning-manual-zone-resources li div { display:grid; gap:2px; min-width:0; }
        .tuning-manual-zone-resources li b { color:var(--text); font-size:10px; overflow-wrap:anywhere; }
        .tuning-manual-zone-resources li small { color:var(--text-muted); font-size:9px; line-height:1.35; }
        .tuning-manual-zone-functions { margin-top:11px; padding-top:10px; border-top:1px solid var(--border); }
        .tuning-manual-zone-functions ul { margin:7px 0 0; padding-left:17px; color:var(--text-muted); font-size:11px; line-height:1.5; }
        .tuning-manual-zone-functions li + li { margin-top:5px; }
        .tuning-manual-principle { display:grid; grid-template-columns:auto 1fr; gap:12px; margin-top:14px; padding:12px 14px; border:1px solid #fed7aa; border-radius:var(--radius-lg); background:#fff7ed; color:#9a3412; font-size:12px; line-height:1.5; }
        .tuning-manual-workflow-note { display:flex; align-items:flex-start; gap:12px; margin-bottom:12px; padding:12px 14px; border:1px solid #bfdbfe; border-radius:var(--radius-lg); background:#eff6ff; color:#1e3a8a; font-size:12px; line-height:1.5; }
        .tuning-manual-workflow-note strong { flex:0 0 auto; }
        .tuning-manual-workflow-list { display:grid; gap:10px; }
        .tuning-manual-workflow-card { padding:14px; border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface); }
        .tuning-manual-workflow-head { display:grid; grid-template-columns:38px minmax(220px,.85fr) minmax(260px,1.15fr); align-items:center; gap:12px; }
        .tuning-manual-step-number { display:grid; place-items:center; width:34px; height:34px; border-radius:10px; background:var(--primary); color:#fff; font-size:13px; font-weight:850; }
        .tuning-manual-step-code { display:block; color:var(--text-muted); font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; font-size:9px; font-weight:800; letter-spacing:.04em; }
        .tuning-manual-workflow-head h3 { margin:3px 0 0; font-size:15px; }
        .tuning-manual-step-zone { justify-self:end; padding:5px 8px; border-radius:999px; background:var(--primary-light); color:var(--primary); font-size:10px; font-weight:750; text-align:right; }
        .tuning-manual-procedure { display:grid; grid-template-columns:130px minmax(0,1fr); gap:8px; align-items:start; margin:12px 0 10px 50px; }
        .tuning-manual-procedure span { color:var(--text-muted); font-size:10px; font-weight:750; text-transform:uppercase; }
        .tuning-manual-procedure code { padding:7px 9px; border:1px solid var(--border); border-radius:8px; background:var(--surface-alt); color:#4338ca; font-size:10px; line-height:1.45; overflow-wrap:anywhere; }
        .tuning-manual-step-details { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:0 0 0 50px; }
        .tuning-manual-step-details > div { padding:9px; border-left:3px solid var(--border-strong); border-radius:0 8px 8px 0; background:var(--surface-alt); }
        .tuning-manual-step-details dt { margin-bottom:4px; color:var(--text); font-size:10px; font-weight:800; }
        .tuning-manual-step-details dd { margin:0; color:var(--text-muted); font-size:11px; line-height:1.5; }
        .tuning-manual-step-details .tuning-manual-step-task-block { grid-column:1 / -1; border-left-color:var(--primary); }
        .tuning-manual-step-task-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px 18px; margin:0; padding:0; list-style:none; counter-reset:workflow-task; }
        .tuning-manual-step-task-list li { position:relative; min-width:0; padding-left:24px; color:var(--text); line-height:1.55; counter-increment:workflow-task; }
        .tuning-manual-step-task-list li::before { content:counter(workflow-task); position:absolute; top:1px; left:0; display:grid; place-items:center; width:17px; height:17px; border-radius:5px; background:var(--primary-light); color:var(--primary); font-size:9px; font-weight:850; }
        .tuning-manual-developer-section + .tuning-manual-developer-section { margin-top:24px; padding-top:22px; border-top:1px solid var(--border); }
        .tuning-manual-developer-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; margin-bottom:12px; }
        .tuning-manual-developer-heading h3 { margin:4px 0 0; font-size:18px; }
        .tuning-manual-developer-heading p { max-width:620px; margin:0; color:var(--text-muted); font-size:11px; line-height:1.5; }
        .tuning-manual-platform-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
        .tuning-manual-platform-card { min-width:0; padding:13px; border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface); }
        .tuning-manual-platform-card h4 { margin:0 0 5px; font-size:14px; }
        .tuning-manual-platform-card > p { min-height:34px; margin:0 0 10px; color:var(--text-muted); font-size:11px; line-height:1.5; }
        .tuning-manual-platform-card > strong { display:block; margin:8px 0 5px; font-size:9px; letter-spacing:.04em; }
        .tuning-manual-code-list, .tuning-manual-symbols { display:flex; flex-wrap:wrap; gap:4px; }
        .tuning-manual-code-list code, .tuning-manual-symbols code { padding:4px 6px; border:1px solid var(--border); border-radius:6px; background:var(--surface-alt); color:#4338ca; font-size:9px; overflow-wrap:anywhere; }
        .tuning-manual-platform-card aside { margin-top:10px; padding:8px; border-left:3px solid var(--primary); background:var(--primary-light); color:var(--text); font-size:10px; line-height:1.45; }
        .tuning-manual-call-flow { display:grid; gap:7px; margin:0; padding:0; list-style:none; counter-reset:none; }
        .tuning-manual-call-flow li { display:grid; grid-template-columns:30px minmax(0,1fr); gap:9px; padding:10px; border:1px solid var(--border); border-radius:10px; background:var(--surface); }
        .tuning-manual-call-number { display:grid; place-items:center; width:27px; height:27px; border-radius:8px; background:var(--primary); color:#fff; font-size:10px; font-weight:850; }
        .tuning-manual-call-flow strong { font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; color:#4338ca; font-size:10px; overflow-wrap:anywhere; }
        .tuning-manual-call-flow small { display:block; margin-top:2px; color:var(--text-muted); font-size:9px; }
        .tuning-manual-call-flow p { margin:5px 0 0; color:var(--text-muted); font-size:11px; line-height:1.5; }
        .tuning-manual-branch-table { display:grid; border:1px solid var(--border); border-radius:var(--radius-lg); overflow:hidden; }
        .tuning-manual-branch-table [role="row"] { display:grid; grid-template-columns:minmax(170px,.7fr) minmax(180px,1fr) minmax(240px,1.3fr); gap:10px; padding:9px 11px; background:var(--surface); font-size:10px; line-height:1.45; }
        .tuning-manual-branch-table [role="row"] + [role="row"] { border-top:1px solid var(--border); }
        .tuning-manual-branch-table code { color:#b91c1c; font-weight:750; overflow-wrap:anywhere; }
        .tuning-manual-branch-table span { color:var(--text-muted); }
        .tuning-manual-trace-list { margin:0; padding:0 0 0 20px; color:var(--text-muted); font-size:11px; line-height:1.6; }
        .tuning-manual-trace-list li + li { margin-top:7px; }
        .tuning-current-progress { display:inline-flex; align-items:center; gap:6px; min-height:32px; max-width:min(680px, 100%); padding:5px 7px 5px 8px; border:1px solid #dbe3ef; border-radius:999px; background:#ffffff; color:#334155; box-shadow:0 3px 10px rgba(15,23,42,.05); }
        .tuning-copy-run-id { padding:3px 7px; border:1px solid #cbd5e1; border-radius:7px; background:#f8fafc; color:#334155; font-size:11px; font-weight:650; cursor:pointer; white-space:nowrap; }
        .tuning-copy-run-id:hover { border-color:#94a3b8; background:#f1f5f9; }
        .tuning-ora-banner { display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid #fecaca; border-radius:10px; background:#fff7f7; color:#991b1b; }
        .tuning-ora-banner code { color:#7f1d1d; font-size:12px; white-space:pre-wrap; overflow-wrap:anywhere; }
        .tuning-current-dot { width:18px; height:18px; display:inline-grid; place-items:center; border-radius:999px; background:#eff6ff; color:#1d4ed8; font-size:10px; font-weight:700; flex:0 0 auto; }
        .tuning-current-running .tuning-current-dot { background:#eff6ff; }
        .tuning-current-done .tuning-current-dot { background:#dcfce7; color:#15803d; }
        .tuning-current-failed .tuning-current-dot { background:#fee2e2; color:#b91c1c; }
        .tuning-current-step { color:#64748b; font-size:10px; font-weight:800; white-space:nowrap; }
        .tuning-current-main { font-size:12px; font-weight:700; color:#172033; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:170px; }
        .tuning-current-detail { font-size:11px; color:#b91c1c; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:210px; }
        .tuning-current-elapsed { padding-left:6px; border-left:1px solid #e2e8f0; color:#475569; font-size:10px; font-variant-numeric:tabular-nums; white-space:nowrap; }
        .tuning-current-total { color:#64748b; font-size:10px; font-weight:650; font-variant-numeric:tabular-nums; white-space:nowrap; }
        .tuning-progress-open { flex:0 0 auto; padding:3px 7px; border:1px solid #cbd5e1; border-radius:999px; background:#fff; color:#334155; font-size:10px; font-weight:750; cursor:pointer; white-space:nowrap; }
        .tuning-progress-open:hover { border-color:#2563eb; color:#1d4ed8; background:#eff6ff; }
        .tuning-progress-drawer[hidden] { display:none; }
        .tuning-progress-drawer { position:fixed; inset:0; z-index:2400; display:flex; justify-content:flex-end; background:rgba(15,23,42,.38); backdrop-filter:blur(2px); }
        .tuning-progress-drawer-panel { width:min(720px, 96vw); height:100%; display:flex; flex-direction:column; background:#f8fafc; color:#172033; box-shadow:-24px 0 64px rgba(15,23,42,.24); animation:tuning-drawer-in .18s ease-out; }
        @keyframes tuning-drawer-in { from { transform:translateX(28px); opacity:.7; } to { transform:translateX(0); opacity:1; } }
        .tuning-progress-drawer-header { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; padding:14px 16px; border-bottom:1px solid #e2e8f0; background:#fff; }
        .tuning-progress-drawer-header > div { min-width:0; }
        .tuning-progress-drawer-eyebrow { display:block; margin-bottom:4px; color:#64748b; font-size:10px; font-weight:800; letter-spacing:.09em; }
        .tuning-progress-drawer-header h3 { margin:0; color:#172033; font-size:18px; line-height:1.3; }
        .tuning-progress-drawer-run { display:flex; align-items:center; gap:6px; min-width:0; margin-top:6px; }
        .tuning-progress-drawer-header code { display:block; min-width:0; color:#64748b; font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; user-select:all; }
        .tuning-progress-drawer-close { flex:0 0 auto; padding:7px 10px; border:1px solid #cbd5e1; border-radius:9px; background:#fff; color:#334155; font-size:12px; font-weight:750; cursor:pointer; }
        .tuning-progress-drawer-close:hover { border-color:#94a3b8; background:#f1f5f9; }
        .tuning-progress-drawer-body { flex:1 1 auto; min-height:0; overflow:auto; padding:10px; }
        .tuning-progress-drawer-current { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:6px; padding:7px 9px; border:1px solid #bfdbfe; border-radius:9px; background:#eff6ff; color:#1e3a8a; font-size:11px; }
        .tuning-progress-drawer-current span { font-weight:750; }
        .tuning-progress-drawer-current strong { font-size:11px; white-space:nowrap; }
        .tuning-before-evidence-activity { margin:0 0 10px; padding:12px; border:1px solid #93c5fd; border-radius:10px; background:#eff6ff; color:#1e3a5f; }
        .tuning-before-evidence-heading { display:flex; align-items:center; justify-content:space-between; gap:10px; }
        .tuning-before-evidence-heading strong { font-size:12px; }
        .tuning-before-evidence-heading span { padding:2px 7px; border-radius:999px; background:#dbeafe; color:#1d4ed8; font-size:9px; font-weight:800; }
        .tuning-before-evidence-tasks { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; margin:10px 0 0; padding:0; list-style:none; }
        .tuning-before-evidence-tasks li { display:flex; flex-direction:column; gap:2px; padding:8px; border:1px solid #bfdbfe; border-radius:8px; background:#fff; }
        .tuning-before-evidence-tasks strong { font-size:10px; color:#1e40af; }
        .tuning-before-evidence-tasks span { font-size:9px; line-height:1.45; color:#475569; }
        .tuning-before-evidence-activity p { margin:9px 0 0; font-size:10px; line-height:1.5; color:#475569; }
        .tuning-before-evidence-activity p strong { color:#b45309; }
        .tuning-progress-step-list { display:grid; gap:4px; }
        .tuning-progress-detail-step { padding:0; border:1px solid #e2e8f0; border-radius:8px; background:#fff; overflow:hidden; }
        .tuning-progress-detail-running { border-color:#93c5fd; background:#eff6ff; }
        .tuning-progress-detail-done, .tuning-progress-detail-completed { border-color:#bbf7d0; background:#f0fdf4; }
        .tuning-progress-detail-skipped { background:#f8fafc; }
        .tuning-progress-detail-failed, .tuning-progress-detail-error, .tuning-progress-detail-blocked, .tuning-progress-detail-rejected { border-color:#fecaca; background:#fff7f7; }
        .tuning-progress-step-head { min-height:32px; display:flex; align-items:center; gap:6px; min-width:0; padding:3px 6px; cursor:pointer; list-style:none; }
        .tuning-progress-step-head::-webkit-details-marker { display:none; }
        .tuning-progress-step-head::after { content:'›'; order:5; flex:0 0 auto; color:#94a3b8; font-size:14px; line-height:1; transition:transform .12s ease; }
        .tuning-progress-detail-step[open] .tuning-progress-step-head::after { transform:rotate(90deg); }
        .tuning-progress-step-number { display:grid; place-items:center; flex:0 0 18px; height:18px; border-radius:6px; background:#e0e7ff; color:#3730a3; font-size:9px; font-weight:800; }
        .tuning-progress-step-title { min-width:0; flex:1 1 auto; color:#172033; font-size:11px; font-weight:750; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .tuning-progress-step-elapsed { flex:0 0 auto; color:#64748b; font-size:9px; font-variant-numeric:tabular-nums; white-space:nowrap; }
        .tuning-progress-step-status { flex:0 0 auto; padding:2px 6px; border-radius:999px; background:#e2e8f0; color:#334155; font-size:9px; font-weight:800; }
        .tuning-progress-detail-running .tuning-progress-step-status { background:#dbeafe; color:#1d4ed8; }
        .tuning-progress-detail-done .tuning-progress-step-status, .tuning-progress-detail-completed .tuning-progress-step-status { background:#dcfce7; color:#15803d; }
        .tuning-progress-detail-failed .tuning-progress-step-status, .tuning-progress-detail-error .tuning-progress-step-status, .tuning-progress-detail-blocked .tuning-progress-step-status, .tuning-progress-detail-rejected .tuning-progress-step-status { background:#fee2e2; color:#b91c1c; }
        .tuning-progress-step-body { padding:0 8px 8px 32px; border-top:1px solid rgba(148,163,184,.18); }
        .tuning-progress-step-code { display:block; margin-top:6px; color:#64748b; font-size:9px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .tuning-progress-step-timing { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:4px; margin:5px 0 0; }
        .tuning-progress-step-timing div { display:flex; gap:5px; min-width:0; font-size:10px; }
        .tuning-progress-step-timing dt { color:#64748b; }
        .tuning-progress-step-timing dd { min-width:0; margin:0; color:#334155; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .tuning-progress-step-log-title { margin-top:5px; color:#475569; font-size:9px; font-weight:750; }
        .tuning-progress-step-logs { margin:2px 0 0; padding:0; list-style:none; }
        .tuning-progress-step-log { color:#475569; font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; font-size:9px; line-height:1.45; overflow-wrap:anywhere; }
        .tuning-llm-call-activity { margin-top:8px; padding:9px; border:1px solid #c7d2fe; border-radius:9px; background:#f5f7ff; }
        .tuning-llm-call-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; }
        .tuning-llm-call-heading strong { color:#312e81; font-size:11px; }
        .tuning-llm-call-heading span { padding:2px 6px; border-radius:999px; background:#e0e7ff; color:#4338ca; font-size:9px; font-weight:800; }
        .tuning-llm-call-activity > p { margin:5px 0 0; color:#64748b; font-size:9px; line-height:1.45; }
        .tuning-llm-call-list { display:grid; gap:6px; margin-top:8px; }
        .tuning-llm-call-card { padding:8px; border:1px solid #dbe3ef; border-left-width:3px; border-radius:8px; background:#fff; }
        .tuning-llm-call-sent { border-left-color:#2563eb; }
        .tuning-llm-call-received { border-left-color:#16a34a; }
        .tuning-llm-call-failed { border-left-color:#dc2626; }
        .tuning-llm-call-summary { display:flex; align-items:center; gap:6px; }
        .tuning-llm-call-summary strong { min-width:0; flex:1 1 auto; color:#172033; font-size:10px; }
        .tuning-llm-call-summary span, .tuning-llm-call-summary em { padding:2px 6px; border-radius:999px; background:#f1f5f9; color:#475569; font-size:8px; font-style:normal; font-weight:750; white-space:nowrap; }
        .tuning-llm-call-received .tuning-llm-call-summary em { background:#dcfce7; color:#15803d; }
        .tuning-llm-call-failed .tuning-llm-call-summary em { background:#fee2e2; color:#b91c1c; }
        .tuning-llm-call-card dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:3px 8px; margin:7px 0 0; }
        .tuning-llm-call-card dl div { display:flex; gap:5px; min-width:0; font-size:9px; }
        .tuning-llm-call-card dt { flex:0 0 auto; color:#64748b; }
        .tuning-llm-call-card dd { min-width:0; margin:0; color:#334155; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .tuning-llm-call-code { margin-top:5px; color:#b91c1c; font-size:9px; }
        .tuning-llm-call-load, .tuning-llm-raw-actions button { margin-top:7px; padding:5px 8px; border:1px solid #a5b4fc; border-radius:7px; background:#fff; color:#3730a3; font-size:9px; font-weight:750; cursor:pointer; }
        .tuning-llm-call-load:disabled { opacity:.55; cursor:wait; }
        .tuning-llm-call-detail:empty { display:none; }
        .tuning-llm-call-detail { margin-top:8px; }
        .tuning-llm-sensitive-note { padding:7px 8px; border:1px solid #fde68a; border-radius:7px; background:#fffbeb; color:#92400e; font-size:9px; line-height:1.45; }
        .tuning-llm-call-error { display:grid; gap:3px; margin-top:6px; padding:7px; border:1px solid #fecaca; border-radius:7px; background:#fff7f7; color:#991b1b; font-size:9px; overflow-wrap:anywhere; }
        .tuning-llm-call-error code { white-space:pre-wrap; overflow-wrap:anywhere; }
        .tuning-llm-raw-block { margin-top:6px; border:1px solid #dbe3ef; border-radius:7px; background:#f8fafc; overflow:hidden; }
        .tuning-llm-raw-block > summary { padding:7px 8px; color:#334155; font-size:9px; font-weight:750; cursor:pointer; }
        .tuning-llm-raw-block > summary span { margin-left:5px; color:#64748b; font-weight:500; }
        .tuning-llm-raw-actions { padding:0 8px 6px; }
        .tuning-llm-raw-actions button { margin-top:0; }
        .tuning-llm-raw-block pre { max-height:420px; margin:0; padding:9px; overflow:auto; border-top:1px solid #dbe3ef; background:#0f172a; color:#e2e8f0; white-space:pre; }
        .tuning-llm-raw-block code { font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; font-size:9px; line-height:1.5; }
        .tuning-llm-raw-empty { margin-top:6px; color:#64748b; font-size:9px; }
        .tuning-pill { color:#475569; border:1px solid #dbe3ef; border-radius:999px; padding:5px 10px; font-size:12px; background:#f8fafc; }
        .tuning-field { display:flex; flex-direction:column; gap:8px; margin-bottom:14px; }
        .tuning-field span { color:var(--text-muted); font-size:13px; font-weight:510; }
        .tuning-controls-row { display:grid; grid-template-columns:repeat(3, minmax(180px, 1fr)); gap:12px; min-width:0; margin-bottom:14px; }
        .tuning-controls-row .tuning-field { min-width:0; margin-bottom:0; }
        .tuning-controls-row .tuning-input { min-width:0; }
        .tuning-execution-option { display:flex; align-items:flex-start; gap:10px; margin:-2px 0 14px; padding:12px 14px; border:1px solid #dbe3ef; border-radius:12px; background:#f8fafc; }
        .tuning-execution-option input { width:18px; height:18px; margin:1px 0 0; accent-color:var(--primary); flex:0 0 auto; }
        .tuning-execution-option-copy { display:flex; flex-direction:column; gap:3px; }
        .tuning-execution-option-copy strong { color:var(--text); font-size:13px; }
        .tuning-execution-option-copy small { color:var(--text-muted); line-height:1.45; }
        .tuning-sql-wrap { position:relative; display:grid; grid-template-columns:52px minmax(0,1fr); border:1px solid var(--border); border-radius:var(--radius-lg); overflow:hidden; background:var(--surface); box-shadow:var(--shadow-sm); }
        .tuning-line-numbers { padding:18px 10px; color:var(--text-muted); background:var(--surface-alt); border-right:1px solid var(--border); text-align:right; user-select:none; white-space:pre; overflow:hidden; font-family:'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace; font-size:14px; line-height:1.62; }
        .tuning-input, .tuning-sql {
          width:100%; box-sizing:border-box; color:var(--text); background:var(--surface);
          border:1px solid var(--border); border-radius:var(--radius-lg); outline:none; box-shadow:var(--shadow-sm);
        }
        .tuning-sql-wrap .tuning-sql { border:0; border-radius:0; box-shadow:none; }
        .tuning-input:focus, .tuning-sql:focus { border-color:var(--primary); box-shadow:0 0 0 2px var(--primary-light); }
        .tuning-sql-wrap:focus-within { border-color:var(--primary); box-shadow:0 0 0 2px var(--primary-light); }
        .tuning-input { padding:12px 14px; }
        select.tuning-input {
          appearance:none; padding-right:42px; background-repeat:no-repeat;
          background-position:right 16px center; background-size:14px 14px;
          background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M3 5.25 7 9l4-3.75' stroke='%236B6660' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
        }
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
          border:1px solid var(--primary); border-radius:var(--radius); padding:12px 16px; color:white; cursor:pointer;
          background:var(--primary); font-weight:590; box-shadow:var(--shadow-sm);
        }
        .tuning-primary:hover { background:var(--primary-hover); border-color:var(--primary-hover); }
        .tuning-secondary { border:1px solid var(--border-strong); border-radius:var(--radius); padding:12px 14px; color:var(--text); background:var(--surface); cursor:pointer; }
        .tuning-secondary:hover { border-color:var(--primary); background:var(--surface-hover); }
        .tuning-primary:focus-visible, .tuning-secondary:focus-visible { outline:2px solid var(--primary); outline-offset:2px; }
        .tuning-primary:disabled, .tuning-secondary:disabled { opacity:.55; cursor:not-allowed; }
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
        .tuning-report-card { min-height:min(82vh, 980px); padding:0 !important; overflow:hidden; }
        .tuning-report-card:not([open]) { min-height:0; }
        .tuning-collapsible-summary .section-title, .tuning-report-collapse-summary .section-title { flex:0 0 auto; font-size:var(--fs-lg); font-weight:600; line-height:1.35; }
        .tuning-report-run-id { min-width:0; flex:1 1 auto; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .tuning-report-collapse-body { border-top:1px solid var(--border); }
        .tuning-report-header { background:var(--surface); border-bottom:1px solid var(--border); }
        .tuning-report-head { display:flex; align-items:flex-start; justify-content:space-between; gap:var(--space-3); flex-wrap:wrap; padding:var(--space-4) var(--space-4) var(--space-2); }
        .tuning-report-title-group { display:flex; flex-direction:column; gap:var(--space-1); min-width:0; color:var(--text); }
        .tuning-report-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-left:auto; }
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
        .tuning-report-mode-badge { display:inline-flex; align-items:center; min-height:24px; padding:3px 8px; border:1px solid var(--border); border-radius:var(--radius); font-size:11px; font-weight:750; white-space:nowrap; }
        .tuning-report-mode-analysis { border-color:#f59e0b; background:#fff7ed; color:#92400e; }
        .tuning-report-mode-runtime { border-color:#16a34a; background:#ecfdf5; color:#166534; }
        .tuning-report-mode-unknown { background:var(--surface-alt); color:var(--text-muted); }
        .tuning-analysis-mode-notice { display:grid; gap:3px; margin:0 0 12px; padding:11px 13px; border:1px solid #f59e0b; border-left-width:4px; border-radius:var(--radius-md); background:#fff7ed; color:#92400e; }
        .tuning-analysis-mode-notice > span { color:#78350f; font-size:12px; }
        .tuning-report-panel h2 { margin:24px 0 10px; padding-bottom:7px; border-bottom:1px solid var(--border); color:var(--text); font-size:20px; }
        .tuning-report-panel h3 { margin:20px 0 8px; font-size:16px; }
        .tuning-verdict-heading { position:relative; display:flex; align-items:center; gap:8px; margin:24px 0 10px; padding-bottom:7px; border-bottom:1px solid var(--border); }
        .tuning-report-panel .tuning-verdict-heading > h2 { margin:0; padding:0; border:0; }
        .tuning-verdict-help-anchor { position:relative; display:inline-flex; align-items:center; }
        .tuning-verdict-help-anchor::after { content:''; display:none; position:absolute; top:calc(100% + 4px); left:5px; z-index:31; width:12px; height:12px; border-left:1px solid var(--border-strong); border-top:1px solid var(--border-strong); background:var(--surface); transform:rotate(45deg); }
        .tuning-verdict-help-open::after { display:block; }
        .tuning-verdict-help-toggle { display:inline-grid; place-items:center; flex:0 0 22px; width:22px; height:22px; padding:0; border:1px solid var(--border-strong); border-radius:999px; background:var(--surface); color:var(--text-muted); font-size:12px; font-weight:800; cursor:pointer; }
        .tuning-verdict-help-toggle:hover { border-color:var(--primary); color:var(--primary); background:var(--primary-light); }
        .tuning-verdict-help-toggle:focus-visible { outline:2px solid var(--primary); outline-offset:2px; }
        .tuning-verdict-summary { display:grid; grid-template-columns:auto minmax(0,1fr); align-items:center; gap:12px; margin:10px 0 18px; padding:12px 14px; border:1px solid var(--border); border-left-width:4px; border-radius:var(--radius-lg); background:var(--surface-alt); }
        .tuning-verdict-summary > div { display:grid; gap:3px; min-width:0; }
        .tuning-verdict-badge { display:inline-flex; align-items:center; min-height:28px; padding:5px 9px; border-radius:var(--radius); font-family:var(--font-mono); font-size:12px; letter-spacing:.01em; white-space:nowrap; }
        .tuning-verdict-meaning { color:var(--text); font-weight:650; }
        .tuning-verdict-action { color:var(--text-muted); font-size:12px; }
        .tuning-verdict-success { border-left-color:var(--success); }
        .tuning-verdict-success .tuning-verdict-badge { background:#e8f5e9; color:var(--success); }
        .tuning-verdict-warning { border-left-color:var(--warning); }
        .tuning-verdict-warning .tuning-verdict-badge { background:#fff7ed; color:var(--warning); }
        .tuning-verdict-danger { border-left-color:var(--danger); }
        .tuning-verdict-danger .tuning-verdict-badge { background:#fef2f2; color:var(--danger); }
        .tuning-verdict-help[hidden] { display:none; }
        .tuning-verdict-help { position:absolute; top:calc(100% + 10px); left:-12px; z-index:30; width:min(720px, calc(100vw - 48px)); max-height:min(62vh, 560px); margin:0; padding:12px; overflow:auto; border:1px solid var(--border-strong); border-radius:var(--radius-lg); background:var(--surface); box-shadow:var(--shadow-md); color:var(--text); font-size:var(--fs-base); font-weight:400; line-height:1.5; }
        .tuning-verdict-help h3 { margin:0 0 10px; }
        .tuning-verdict-guide { width:100%; border-collapse:collapse; white-space:normal; }
        .tuning-verdict-guide th, .tuning-verdict-guide td { padding:8px 10px; border:1px solid var(--border); text-align:left; vertical-align:top; }
        .tuning-verdict-guide th { background:var(--surface-alt); font-size:12px; }
        .tuning-verdict-guide td:first-child { font-family:var(--font-mono); font-size:11px; font-weight:700; white-space:nowrap; }
        .tuning-verdict-guide-current { background:var(--primary-light); }
        .tuning-report-panel p { margin:8px 0 14px; white-space:pre-wrap; overflow-wrap:anywhere; }
        .tuning-report-panel ul, .tuning-report-panel ol { margin:8px 0 16px; padding-left:24px; }
        .tuning-report-code { max-width:100%; margin:10px 0 18px; padding:14px; overflow:auto; border:1px solid #dbe3ef; border-radius:10px; background:#0f172a; color:#e2e8f0; white-space:pre; }
        .tuning-report-code code { font-family:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; font-size:12px; line-height:1.55; }
        .tuning-report-table { width:100%; margin:10px 0 20px; border-collapse:collapse; display:block; overflow-x:auto; white-space:nowrap; }
        .tuning-report-table th, .tuning-report-table td { padding:9px 11px; border:1px solid var(--border); text-align:left; }
        .tuning-report-table th { background:var(--surface-alt); font-weight:750; }
        .tuning-report-table tbody tr:nth-child(even) { background:var(--surface-alt); }
        .tuning-report-empty { padding:24px; border:1px dashed var(--border); border-radius:var(--radius-lg); color:var(--text-muted); text-align:center; }
        .tuning-sql-diff-summary { padding:10px 12px; border:1px solid var(--border); border-radius:var(--radius-md); background:var(--surface-alt); color:var(--text-muted); font-size:12px; }
        .tuning-sql-change-explanation { margin:10px 0 12px; padding:12px 14px; border-left:3px solid var(--primary); border-radius:0 var(--radius-md) var(--radius-md) 0; background:var(--primary-light); }
        .tuning-sql-change-explanation h3 { margin:0 0 6px; color:var(--text); font-size:14px; }
        .tuning-sql-change-explanation ul { margin:0; padding-left:20px; color:var(--text); }
        .tuning-sql-side-by-side { display:grid; grid-template-columns:repeat(2,minmax(420px,1fr)); gap:10px; max-width:100%; overflow-x:auto; align-items:start; }
        .tuning-sql-diff-pane { min-width:0; overflow-x:auto; border:1px solid var(--border); border-radius:var(--radius-md); background:var(--surface); }
        .tuning-sql-diff-pane-title { position:sticky; top:0; z-index:1; margin:0 !important; padding:8px 10px; border-bottom:1px solid var(--border); background:var(--surface-alt); font-size:12px !important; }
        .tuning-sql-diff-pane-body { min-width:max-content; }
        .tuning-sql-diff-line { display:grid; grid-template-columns:42px 18px minmax(360px,1fr); min-height:23px; border-bottom:1px solid rgba(148,163,184,.18); font-family:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace; font-size:11px; line-height:1.55; }
        .tuning-sql-diff-line:last-child { border-bottom:0; }
        .tuning-sql-diff-line-number { padding:3px 6px; border-right:1px solid rgba(148,163,184,.22); color:#94a3b8; text-align:right; user-select:none; }
        .tuning-sql-diff-marker { padding:3px 2px; font-weight:800; text-align:center; user-select:none; }
        .tuning-sql-diff-code { padding:3px 9px 3px 4px; color:var(--text); white-space:pre; }
        .tuning-sql-diff-empty { background:repeating-linear-gradient(135deg,transparent,transparent 5px,rgba(148,163,184,.05) 5px,rgba(148,163,184,.05) 10px); }
        .tuning-sql-diff-add { background:#ecfdf5; }
        .tuning-sql-diff-add .tuning-sql-diff-marker, .tuning-sql-diff-add .tuning-sql-diff-code { color:#166534; }
        .tuning-sql-diff-remove { background:#fff1f2; }
        .tuning-sql-diff-remove .tuning-sql-diff-marker, .tuning-sql-diff-remove .tuning-sql-diff-code { color:#9f1239; }
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
          .tuning-manual-architecture-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
          .tuning-manual-zone::after { display:none; }
          .tuning-manual-step-details { grid-template-columns:1fr; }
          .tuning-manual-platform-grid { grid-template-columns:1fr; }
        }
        @media (max-width: 720px) {
          .tuning-shell {
            min-height: calc(100dvh - 56px);
            margin: calc(var(--space-3, 12px) * -1);
            padding: 12px;
            background:var(--surface-alt);
          }
          .tuning-hero {
            display:block;
            margin-bottom:12px;
          }
          .tuning-hero-actions, .tuning-top-actions { justify-content:flex-start; margin-top:8px; }
          .tuning-manual-dialog { place-items:end center; padding:0; }
          .tuning-manual-panel { width:100vw; max-height:94dvh; border-radius:18px 18px 0 0; }
          .tuning-manual-header { padding:16px; }
          .tuning-manual-header p { font-size:12px; }
          .tuning-manual-tabs { position:sticky; top:0; z-index:2; grid-template-columns:repeat(3,minmax(0,1fr)); padding:9px 16px; }
          .tuning-manual-tab::after { display:none; }
          .tuning-manual-content { padding:14px; }
          .tuning-manual-intro { display:block; }
          .tuning-manual-flow { justify-content:flex-start; margin-top:10px; }
          .tuning-manual-architecture-grid { grid-template-columns:1fr; }
          .tuning-manual-zone h3, .tuning-manual-zone code { min-height:0; }
          .tuning-manual-principle { grid-template-columns:1fr; gap:5px; }
          .tuning-manual-workflow-note { display:grid; gap:4px; }
          .tuning-manual-workflow-head { grid-template-columns:34px minmax(0,1fr); }
          .tuning-manual-step-zone { grid-column:2; justify-self:start; text-align:left; }
          .tuning-manual-procedure { grid-template-columns:1fr; margin-left:0; }
          .tuning-manual-step-details { margin-left:0; }
          .tuning-manual-step-task-list { grid-template-columns:1fr; }
          .tuning-manual-developer-heading { display:block; }
          .tuning-manual-developer-heading p { margin-top:7px; }
          .tuning-manual-branch-table [role="row"] { grid-template-columns:1fr; gap:4px; }
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
          .tuning-card { padding:0; border-radius:var(--radius-lg); box-shadow:none; }
          .tuning-card-title { margin:0; }
          .tuning-collapsible-body { padding:var(--space-3); }
          .tuning-collapsible-summary, .tuning-report-collapse-summary { min-height:44px; padding:var(--space-3); }
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
          .tuning-result .tuning-report-card { padding:0 !important; border-radius:var(--radius-lg); }
          .tuning-result .code-block {
            max-height: 62vh !important;
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap !important;
            overflow-wrap: anywhere;
          }
          .tuning-report-head { display:grid; grid-template-columns:1fr; }
          .tuning-report-actions { display:grid; grid-template-columns:1fr; width:100%; margin-left:0; }
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
          .tuning-sql-side-by-side { grid-template-columns:repeat(2,minmax(340px,1fr)); }
          .tuning-sql-diff-line { grid-template-columns:34px 16px minmax(280px,1fr); font-size:10px; }
        }
        @media (max-width: 700px) {
          .tuning-current-progress { border-radius:14px; }
          .tuning-current-detail { display:none; }
          .tuning-progress-open { margin-left:auto; }
          .tuning-progress-drawer { align-items:flex-end; }
          .tuning-before-evidence-tasks { grid-template-columns:1fr; }
          .tuning-progress-drawer-panel { width:100vw; height:min(92dvh, 920px); border-radius:18px 18px 0 0; }
          .tuning-progress-drawer-header { padding:16px; }
          .tuning-progress-drawer-body { padding:12px; }
          .tuning-progress-step-code { display:none; }
          .tuning-progress-step-timing { grid-template-columns:1fr; }
          .tuning-result .tuning-report-card { padding:0 !important; border-radius:var(--radius-lg); }
          .tuning-report-header { min-width:0; }
          .tuning-report-head { grid-template-columns:1fr; padding:var(--space-3) var(--space-3) var(--space-2); }
          .tuning-report-actions { grid-template-columns:1fr; gap:var(--space-2); }
          .tuning-report-status-slot { padding-inline:var(--space-3); padding-bottom:var(--space-3); }
          .tuning-report-status-slot .tuning-current-progress { align-items:flex-start; border-radius:var(--radius-lg); }
          .tuning-report-tabs-host { padding-inline:var(--space-3); padding-bottom:var(--space-3); }
          .tuning-report-tablist { width:100%; overflow-x:auto; flex-wrap:nowrap; }
          .tuning-report-tab { min-height:32px; padding:6px 10px; }
          .tuning-report-scroll { padding-inline:var(--space-3); padding-bottom:var(--space-4); }
          .tuning-report-panel { padding:var(--space-3) 0 var(--space-4); }
          .tuning-verdict-summary { grid-template-columns:1fr; gap:8px; }
          .tuning-verdict-help { left:-64px; width:calc(100vw - 48px); padding:8px; }
          .tuning-verdict-guide { min-width:640px; }
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
          .tuning-card { padding:0; border-radius:var(--radius-lg); box-shadow:none; }
          .tuning-card-title { font-size:14px; margin:0; }
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
          .tuning-card { padding:0; border-radius:var(--radius-lg); box-shadow:none; }
          .tuning-card-title { margin:0; font-size:13px; }
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
              <button class="tuning-secondary" id="asta-manual-open" type="button" aria-haspopup="dialog" aria-controls="asta-manual-dialog">매뉴얼 및 사용설명</button>
              <button class="tuning-primary" id="asta-run" title="SQL Formatting 후 ADB ORDS/PLSQL AI 분석을 실행합니다">AI 분석 실행</button>
              <button class="tuning-secondary" id="asta-reset" type="button" hidden>신규분석(초기화)</button>
              <button class="tuning-secondary" id="asta-download-report" type="button" hidden>보고서 다운로드</button>
              <button class="tuning-secondary tuning-secret-only" id="asta-sql-only-llm" type="button" hidden title="SQL 텍스트만 선택한 LLM profile로 전송합니다">SQL만 LLM</button>
              <span id="asta-current-progress" class="tuning-progress-anchor" aria-live="polite" hidden></span>
            </div>
          </div>
        </div>

        <div class="tuning-grid">
          <details id="asta-input-section" class="tuning-card tuning-collapsible-section" open>
            <summary class="tuning-card-title tuning-collapsible-summary">
              <span class="section-title">SQL 분석 입력</span>
            </summary>
            <div class="tuning-collapsible-body">
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
                <small id="asta-workload-description" class="muted">OLTP: Buffer Reads를 우선하며 후보가 원본보다 느려지는 경우에만 1초/300ms tradeoff를 제한합니다.</small>
              </label>
              <label class="tuning-field" for="asta-sample-sql">
                <span>샘플 튜닝대상 SQL</span>
                <select class="tuning-input" id="asta-sample-sql">
                  <option value="">직접 입력</option>
                  ${ASTA_SAMPLE_SQLS.map((sample) => `<option value="${escapeHtml(sample.id)}">${escapeHtml(sample.label)}</option>`).join("")}
                </select>
              </label>
            </div>
            <label class="tuning-execution-option" for="asta-execute-source-sql">
              <input id="asta-execute-source-sql" type="checkbox" />
              <span class="tuning-execution-option-copy">
                <strong>소스 DB에서 SQL을 실제 실행하여 검증</strong>
                <small>기본 해제: EXPLAIN PLAN 예상 실행계획과 객체 통계·인덱스만 수집합니다. 실행 시간·Buffer Gets·결과 동등성은 검증하지 않습니다.</small>
              </span>
            </label>
            <label class="tuning-field" for="asta-tuning-notes">
              <span>AI 참고사항 (선택)</span>
              <textarea class="tuning-input tuning-notes" id="asta-tuning-notes" rows="3" spellcheck="false" placeholder="예: 특정 테이블/인덱스/조건을 중점 검토, 업무상 유지해야 하는 조건, 의심 병목 등"></textarea>
            </label>
            <label class="tuning-field" for="asta-sql">
              <span>SQL</span>
              <textarea class="tuning-sql" id="asta-sql" rows="10" spellcheck="false" placeholder="SELECT ..."></textarea>
            </label>
            </div>
          </details>
        </div>

        <div id="asta-result" class="tuning-result stack"></div>

        <section id="asta-manual-dialog" class="tuning-manual-dialog" role="dialog" aria-modal="true" aria-labelledby="asta-manual-title" hidden>
          <div class="tuning-manual-panel">
            <header class="tuning-manual-header">
              <div>
                <span class="tuning-manual-eyebrow">ASTA Guide</span>
                <h2 id="asta-manual-title">매뉴얼 및 사용설명</h2>
                <p>구성 영역별 책임, 실제 11단계 흐름, 개발자용 파일·함수·추적 절차를 확인합니다.</p>
              </div>
              <button class="tuning-manual-close" type="button" aria-label="매뉴얼 닫기">닫기</button>
            </header>
            <div class="tuning-manual-tabs" role="tablist" aria-label="ASTA 도움말 목차">
              <button id="asta-manual-tab-architecture" class="tuning-manual-tab" type="button" role="tab" aria-selected="true" aria-controls="asta-manual-architecture" data-manual-tab="architecture"><span class="tuning-manual-tab-index">01</span><span class="tuning-manual-tab-label">아키텍처</span></button>
              <button id="asta-manual-tab-workflow" class="tuning-manual-tab" type="button" role="tab" aria-selected="false" aria-controls="asta-manual-workflow" data-manual-tab="workflow" tabindex="-1"><span class="tuning-manual-tab-index">02</span><span class="tuning-manual-tab-label">11단계 Workflow</span></button>
              <button id="asta-manual-tab-developer" class="tuning-manual-tab" type="button" role="tab" aria-selected="false" aria-controls="asta-manual-developer" data-manual-tab="developer" tabindex="-1"><span class="tuning-manual-tab-index">03</span><span class="tuning-manual-tab-label">개발자 실행 추적</span></button>
            </div>
            <div class="tuning-manual-content">
              <section id="asta-manual-architecture" class="tuning-manual-panel-view" role="tabpanel" aria-labelledby="asta-manual-tab-architecture">
                ${renderArchitectureManual()}
              </section>
              <section id="asta-manual-workflow" class="tuning-manual-panel-view" role="tabpanel" aria-labelledby="asta-manual-tab-workflow" hidden>
                ${renderWorkflowManual()}
              </section>
              <section id="asta-manual-developer" class="tuning-manual-panel-view" role="tabpanel" aria-labelledby="asta-manual-tab-developer" hidden>
                ${renderDeveloperManual()}
              </section>
            </div>
          </div>
        </section>
      </section>`;

    const profileInput = document.getElementById("asta-ai-profile");
    const workloadSelect = document.getElementById("asta-workload-type");
    const sampleInput = document.getElementById("asta-sample-sql");
    const executeSourceSqlInput = document.getElementById("asta-execute-source-sql");
    const notesInput = document.getElementById("asta-tuning-notes");
    const sqlInput = document.getElementById("asta-sql");
    const lineNumbers = document.getElementById("asta-line-numbers");
    const result = document.getElementById("asta-result");
    const progressTarget = document.getElementById("asta-current-progress");
    renderProgressStack(progressTarget, { status: "READY", progress: DEFAULT_STEPS });

    const manualDialog = document.getElementById("asta-manual-dialog");
    const manualTabs = Array.from(manualDialog?.querySelectorAll("[data-manual-tab]") || []);
    let manualReturnFocus = null;

    /** 매뉴얼 dialog의 아키텍처/Workflow 탭을 전환하고 roving focus를 유지한다. */
    function setAstaManualTab(tabName, moveFocus = false) {
      const selectedName = ["architecture", "workflow", "developer"].includes(tabName) ? tabName : "architecture";
      manualTabs.forEach((tab) => {
        const selected = tab.dataset.manualTab === selectedName;
        tab.setAttribute("aria-selected", selected ? "true" : "false");
        tab.tabIndex = selected ? 0 : -1;
        if (selected && moveFocus) tab.focus();
      });
      ["architecture", "workflow", "developer"].forEach((name) => {
        const panel = document.getElementById(`asta-manual-${name}`);
        if (panel) panel.hidden = name !== selectedName;
      });
      const content = manualDialog?.querySelector(".tuning-manual-content");
      if (content) content.scrollTop = 0;
    }

    /** ASTA 매뉴얼 팝업을 열고 닫기 전 포커스를 기억한다. */
    function openAstaManualDialog(tabName = "architecture") {
      if (!manualDialog) return;
      manualReturnFocus = document.activeElement;
      setAstaManualTab(tabName);
      manualDialog.hidden = false;
      document.body.classList.add("tuning-manual-open");
      manualDialog.querySelector(".tuning-manual-close")?.focus();
    }

    /** 팝업을 닫고 열기 버튼 또는 직전 control로 포커스를 복원한다. */
    function closeAstaManualDialog() {
      if (!manualDialog || manualDialog.hidden) return;
      manualDialog.hidden = true;
      document.body.classList.remove("tuning-manual-open");
      manualReturnFocus?.focus?.();
      manualReturnFocus = null;
    }

    document.getElementById("asta-manual-open")?.addEventListener("click", () => openAstaManualDialog());
    manualDialog?.querySelector(".tuning-manual-close")?.addEventListener("click", closeAstaManualDialog);
    manualTabs.forEach((tab, index) => {
      tab.addEventListener("click", () => setAstaManualTab(tab.dataset.manualTab));
      tab.addEventListener("keydown", (event) => {
        let nextIndex = null;
        if (event.key === "ArrowRight") nextIndex = (index + 1) % manualTabs.length;
        if (event.key === "ArrowLeft") nextIndex = (index - 1 + manualTabs.length) % manualTabs.length;
        if (event.key === "Home") nextIndex = 0;
        if (event.key === "End") nextIndex = manualTabs.length - 1;
        if (nextIndex === null) return;
        event.preventDefault();
        setAstaManualTab(manualTabs[nextIndex].dataset.manualTab, true);
      });
    });
    manualDialog?.addEventListener("click", (event) => {
      if (event.target === manualDialog) closeAstaManualDialog();
    });
    manualDialog?.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeAstaManualDialog();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(manualDialog.querySelectorAll('button:not([disabled]):not([tabindex="-1"]), [href], [tabindex]:not([tabindex="-1"])'))
        .filter((element) => !element.hidden && element.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

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
      if (executeSourceSqlInput) executeSourceSqlInput.checked = false;
      updateWorkloadDescription("OLTP");
      const inputSection = document.getElementById("asta-input-section");
      if (inputSection) inputSection.open = true;
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
        : "OLTP: Buffer Reads를 우선하며 후보가 원본보다 느려지는 경우에만 1초/300ms tradeoff를 제한합니다.";
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
      window.__astaRunLookupBaseUrl = baseUrl;
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
        executeSourceSqlInput?.checked
          ? "원본 SQL 실제 실행 Evidence 수집: metrics, SQL_ID, XPLAN, object 통계"
          : "원본 SQL 미실행: EXPLAIN PLAN 예상계획과 객체 통계·인덱스 수집",
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
            execute_source_sql: Boolean(executeSourceSqlInput?.checked),
            before_evidence_mode: "MINIMAL",
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
              execute_source_sql: Boolean(executeSourceSqlInput?.checked),
              before_evidence_mode: "MINIMAL",
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
          if (!isEstimatedPlanAnalysisOnly(data)) {
            window.Toast?.show?.("ASTA 분석이 완료되었습니다.", "success");
          } else {
            window.Toast?.show?.("ASTA 미실행 분석이 완료되었습니다. 성능 개선 여부는 미검증입니다.", "success");
          }
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
