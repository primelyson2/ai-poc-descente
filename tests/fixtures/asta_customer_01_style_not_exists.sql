/* SESL0640.selectList 고객 SQL의 STYLE CTE 원문 구간 */
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
SELECT STYLE_CD FROM STYLE
