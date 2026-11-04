-- =============================================================================
-- SOAP: Synthetic Operational Army Platform
-- Layer 3: Kimball Dimensional Star Schema & Executive Analytics Views
-- =============================================================================
-- Purpose:
--   Gold analytics layer (`mart_readiness`) optimized for BI, Commander Readiness
--   Dashboards (Vantage / cArmy style), and cross-ERP financial reconciliation.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS mart_readiness;

-- Dimension 1: Flattened Unit Command Hierarchy (BDE -> BN -> CO)
CREATE TABLE IF NOT EXISTS mart_readiness.dim_unit (
    unit_key                SERIAL PRIMARY KEY,
    uic                     CHAR(6) NOT NULL UNIQUE,
    unit_name               VARCHAR(160) NOT NULL,
    short_name              VARCHAR(32) NOT NULL,
    echelon                 VARCHAR(16) NOT NULL,
    unit_type               VARCHAR(32) NOT NULL,
    parent_uic              CHAR(6),
    battalion_uic           CHAR(6),
    brigade_uic             CHAR(6),
    command_path            TEXT NOT NULL,
    station_installation    VARCHAR(80) NOT NULL,
    cost_center             VARCHAR(32) NOT NULL,
    authorized_personnel    INTEGER NOT NULL
);

-- Dimension 2: Soldier Readiness & Talent Dimension
CREATE TABLE IF NOT EXISTS mart_readiness.dim_soldier (
    soldier_key             SERIAL PRIMARY KEY,
    edipi_dod_id            CHAR(10) NOT NULL UNIQUE,
    full_name               VARCHAR(130) NOT NULL,
    pay_grade               VARCHAR(6) NOT NULL,
    rank_code               VARCHAR(8) NOT NULL,
    personnel_category      VARCHAR(16) NOT NULL,
    primary_mos             VARCHAR(8) NOT NULL,
    security_clearance      VARCHAR(16) NOT NULL,
    current_uic             CHAR(6) NOT NULL,
    deployable_flag         BOOLEAN NOT NULL,
    duty_status             VARCHAR(32) NOT NULL,
    last_acft_score         INTEGER,
    weapons_qual_level      VARCHAR(24)
);

-- Dimension 3: Serialized Pacing & Tactical Equipment Dimension
CREATE TABLE IF NOT EXISTS mart_readiness.dim_equipment (
    equipment_key           SERIAL PRIMARY KEY,
    equipment_num           VARCHAR(32) NOT NULL UNIQUE,
    serial_num              VARCHAR(32) NOT NULL,
    bumper_no               VARCHAR(24) NOT NULL,
    lin                     VARCHAR(12) NOT NULL,
    nsn                     VARCHAR(20) NOT NULL,
    nomenclature            VARCHAR(160) NOT NULL,
    equipment_category      VARCHAR(32) NOT NULL,
    erc_code                CHAR(1) NOT NULL,
    is_pacing_item          BOOLEAN NOT NULL,
    owning_uic              CHAR(6) NOT NULL,
    current_status          VARCHAR(8) NOT NULL,
    replacement_cost_usd    NUMERIC(14, 2) NOT NULL
);

-- Fact 1: Monthly Unit Status Readiness (NetUSR Star Fact)
CREATE TABLE IF NOT EXISTS mart_readiness.fact_unit_usr_monthly (
    usr_report_id           VARCHAR(32) PRIMARY KEY,
    unit_key                INTEGER NOT NULL REFERENCES mart_readiness.dim_unit(unit_key),
    uic                     CHAR(6) NOT NULL,
    report_month            CHAR(7) NOT NULL,
    authorized_strength     INTEGER NOT NULL,
    assigned_strength       INTEGER NOT NULL,
    deployable_strength     INTEGER NOT NULL,
    personnel_fill_pct      NUMERIC(5, 2) NOT NULL,
    equipment_on_hand_count INTEGER NOT NULL,
    equipment_fmc_count     INTEGER NOT NULL,
    equipment_fmc_pct       NUMERIC(5, 2) NOT NULL,
    p_level                 CHAR(3) NOT NULL,
    s_level                 CHAR(3) NOT NULL,
    r_level                 CHAR(3) NOT NULL,
    t_level                 CHAR(3) NOT NULL,
    overall_c_rating        CHAR(3) NOT NULL,
    c_rating_numeric        INTEGER NOT NULL,
    rearmm_phase            VARCHAR(24) NOT NULL
);

-- Fact 2: Cross-ERP Maintenance, Supply & Financial Cost Fact
-- Integrates GCSS-Army Work Orders + Class IX MILSTRIP Requisitions + GFEBS Obligations
CREATE TABLE IF NOT EXISTS mart_readiness.fact_maintenance_supply_finance (
    work_order_id           VARCHAR(32) PRIMARY KEY,
    unit_key                INTEGER NOT NULL REFERENCES mart_readiness.dim_unit(unit_key),
    equipment_key           INTEGER NOT NULL REFERENCES mart_readiness.dim_equipment(equipment_key),
    uic                     CHAR(6) NOT NULL,
    equipment_num           VARCHAR(32) NOT NULL,
    nmc_type                VARCHAR(8) NOT NULL,
    order_status            VARCHAR(32) NOT NULL,
    downtime_days           NUMERIC(8, 2),
    actual_man_hours        NUMERIC(8, 2) NOT NULL,
    milstrip_doc_count      INTEGER NOT NULL DEFAULT 0,
    parts_extended_cost_usd NUMERIC(14, 2) NOT NULL DEFAULT 0,
    gfebs_obligated_usd     NUMERIC(14, 2) NOT NULL DEFAULT 0,
    gfebs_disbursed_usd     NUMERIC(14, 2) NOT NULL DEFAULT 0,
    financial_variance_usd  NUMERIC(14, 2) NOT NULL DEFAULT 0
);

-- Executive View 1: Brigade Combat Team Readiness & Cost Rollup
CREATE OR REPLACE VIEW mart_readiness.vw_bct_readiness_summary AS
SELECT
    du.echelon,
    du.uic,
    du.short_name,
    du.unit_type,
    f.report_month,
    f.rearmm_phase,
    f.overall_c_rating,
    f.p_level,
    f.r_level,
    f.t_level,
    f.personnel_fill_pct,
    f.equipment_fmc_pct
FROM mart_readiness.fact_unit_usr_monthly f
JOIN mart_readiness.dim_unit du ON du.unit_key = f.unit_key
ORDER BY f.report_month DESC, du.uic;

-- Executive View 2: Cross-System GCSS-Army vs. GFEBS Financial Reconciliation
CREATE OR REPLACE VIEW mart_readiness.vw_cross_erp_reconciliation AS
SELECT
    du.uic,
    du.short_name,
    du.cost_center,
    COUNT(f.work_order_id) AS total_work_orders,
    SUM(CASE WHEN f.nmc_type = 'NMCS' THEN 1 ELSE 0 END) AS nmcs_supply_deadlines,
    ROUND(AVG(f.downtime_days), 2) AS avg_downtime_days,
    SUM(f.parts_extended_cost_usd) AS gcssa_requisition_total_usd,
    SUM(f.gfebs_obligated_usd) AS gfebs_obligated_total_usd,
    SUM(f.gfebs_disbursed_usd) AS gfebs_disbursed_total_usd,
    SUM(f.financial_variance_usd) AS cross_erp_unreconciled_variance_usd
FROM mart_readiness.fact_maintenance_supply_finance f
JOIN mart_readiness.dim_unit du ON du.unit_key = f.unit_key
GROUP BY du.uic, du.short_name, du.cost_center
ORDER BY gfebs_obligated_total_usd DESC;
