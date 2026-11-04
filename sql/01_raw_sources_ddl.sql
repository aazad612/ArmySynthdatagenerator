-- =============================================================================
-- SOAP: Synthetic Operational Army Platform
-- Layer 1: Raw ERP Source Landing Schema (PostgreSQL 15+)
-- =============================================================================
-- Purpose:
--   Unconstrained landing tables for raw CDC and batch extracts from 5 U.S. Army
--   systems of record: FMSWeb, IPPS-A, GCSS-Army, DTMS/NetUSR, and GFEBS.
--   Foreign keys are intentionally omitted in the raw layer so late-arriving
--   dimensions, duplicate CDC replays, and dirty UIC strings can land safely
--   for downstream auditing and canonical normalization.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS raw_erp;

-- 1. FMSWeb: Force Structure & MTOE Authorizations
CREATE TABLE IF NOT EXISTS raw_erp.raw_fmsweb_units (
    uic                     TEXT,
    parent_uic              TEXT,
    unit_name               TEXT,
    short_name              TEXT,
    echelon                 TEXT,
    unit_type               TEXT,
    station_installation    TEXT,
    cost_center             TEXT,
    mtoe_doc_no             TEXT,
    authorized_personnel    INTEGER,
    effective_fy            INTEGER,
    _source_system          TEXT,
    _batch_id               TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_erp.raw_fmsweb_mtoe_billets (
    billet_id               TEXT,
    uic                     TEXT,
    para_no                 TEXT,
    line_no                 TEXT,
    position_title          TEXT,
    mos_auth                TEXT,
    grade_auth              TEXT,
    auth_qty                INTEGER,
    _source_system          TEXT,
    _batch_id               TEXT
);

CREATE TABLE IF NOT EXISTS raw_erp.raw_fmsweb_mtoe_equipment (
    mtoe_equip_auth_id      TEXT,
    uic                     TEXT,
    lin                     TEXT,
    nsn                     TEXT,
    tamcn                   TEXT,
    nomenclature            TEXT,
    erc_code                TEXT,
    authorized_qty          INTEGER,
    _source_system          TEXT,
    _batch_id               TEXT
);

-- 2. IPPS-A: Integrated Personnel and Pay System - Army
CREATE TABLE IF NOT EXISTS raw_erp.raw_ippsa_soldiers (
    edipi_dod_id            TEXT,
    first_name              TEXT,
    last_name               TEXT,
    component               TEXT,
    current_uic             TEXT,
    billet_id               TEXT,
    pay_grade               TEXT,
    rank_code               TEXT,
    personnel_category      TEXT,
    primary_mos             TEXT,
    security_clearance      TEXT,
    deployable_flag         BOOLEAN,
    pulhes_profile          TEXT,
    duty_status             TEXT,
    last_acft_score         INTEGER,
    weapons_qual_level      TEXT,
    promotions_count        INTEGER,
    pcs_moves_count         INTEGER,
    _cdc_op                 TEXT,
    _cdc_sequence           INTEGER,
    _source_system          TEXT,
    _batch_id               TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_erp.raw_ippsa_assignments (
    assignment_id           TEXT,
    edipi_dod_id            TEXT,
    uic                     TEXT,
    billet_id               TEXT,
    assignment_type         TEXT,
    duty_status             TEXT,
    pcs_order_no            TEXT,
    effective_start_date    DATE,
    effective_end_date      DATE,
    _cdc_op                 TEXT,
    _cdc_sequence           INTEGER,
    _source_system          TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

-- 3. GCSS-Army: Logistics, Property Book, Maintenance & Class IX Supply
CREATE TABLE IF NOT EXISTS raw_erp.raw_gcssa_equipment (
    equipment_num           TEXT,
    serial_num              TEXT,
    bumper_no               TEXT,
    nsn                     TEXT,
    lin                     TEXT,
    tamcn                   TEXT,
    nomenclature            TEXT,
    equipment_category      TEXT,
    erc_code                TEXT,
    owning_uic              TEXT,
    operational_status      TEXT,
    odometer_miles          NUMERIC(12, 2),
    engine_hours            NUMERIC(12, 2),
    replacement_cost_usd    NUMERIC(14, 2),
    dispatch_cycles         INTEGER,
    _cdc_op                 TEXT,
    _cdc_sequence           INTEGER,
    _source_system          TEXT,
    _batch_id               TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_erp.raw_gcssa_work_orders (
    work_order_id           TEXT,
    equipment_num           TEXT,
    serial_num              TEXT,
    owning_uic              TEXT,
    fault_code              TEXT,
    fault_description       TEXT,
    maintenance_level       TEXT,
    nmc_type                TEXT,
    order_status            TEXT,
    opened_ts               TIMESTAMPTZ,
    closed_ts               TIMESTAMPTZ,
    actual_man_hours        NUMERIC(8, 2),
    _cdc_op                 TEXT,
    _cdc_sequence           INTEGER,
    _source_system          TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_erp.raw_gcssa_supply_requisitions (
    doc_number_milstrip     TEXT,
    work_order_id           TEXT,
    equipment_num           TEXT,
    owning_uic              TEXT,
    part_nsn                TEXT,
    part_nomenclature       TEXT,
    qty_ordered             INTEGER,
    unit_price_usd          NUMERIC(14, 2),
    extended_cost_usd       NUMERIC(14, 2),
    priority_designator     TEXT,
    supply_status_code      TEXT,
    requisition_date        DATE,
    _source_system          TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

-- 4. DTMS / NetUSR: Training & Readiness Reporting
CREATE TABLE IF NOT EXISTS raw_erp.raw_dtms_training_events (
    event_id                TEXT,
    uic                     TEXT,
    edipi_dod_id            TEXT,
    training_type           TEXT,
    metl_task_id            TEXT,
    raw_score               INTEGER,
    qualification_rating    TEXT,
    event_date              DATE,
    _source_system          TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_erp.raw_dtms_usr_readiness (
    usr_report_id           TEXT,
    uic                     TEXT,
    report_month            TEXT,
    authorized_strength     INTEGER,
    assigned_strength       INTEGER,
    deployable_strength     INTEGER,
    personnel_fill_pct      NUMERIC(5, 2),
    equipment_on_hand_count INTEGER,
    equipment_fmc_count     INTEGER,
    equipment_fmc_pct       NUMERIC(5, 2),
    p_level                 TEXT,
    s_level                 TEXT,
    r_level                 TEXT,
    t_level                 TEXT,
    overall_c_rating        TEXT,
    rearmm_phase            TEXT,
    _source_system          TEXT,
    _batch_id               TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);

-- 5. GFEBS: General Fund Enterprise Business System Financials
CREATE TABLE IF NOT EXISTS raw_erp.raw_gfebs_obligations (
    obligation_doc_no       TEXT,
    uic                     TEXT,
    cost_center             TEXT,
    fund_code               TEXT,
    element_of_resource     TEXT,
    linked_milstrip_doc     TEXT,
    vendor_cage_code        TEXT,
    obligated_amount_usd    NUMERIC(14, 2),
    disbursed_amount_usd    NUMERIC(14, 2),
    fiscal_year             INTEGER,
    posting_date            DATE,
    _source_system          TEXT,
    _ingested_at            TIMESTAMPTZ DEFAULT NOW()
);
