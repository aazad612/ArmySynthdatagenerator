-- =============================================================================
-- SOAP: Synthetic Operational Army Platform
-- Layer 2: Enterprise Canonical 3NF + SCD2 Data Model (PostgreSQL 15+)
-- =============================================================================
-- Purpose:
--   Single version of truth integrating FMSWeb, IPPS-A, GCSS-Army, DTMS, and GFEBS.
--   Enforces strict referential integrity, domain check constraints, standardized
--   6-character Unit Identification Codes (UIC), 10-digit DODID/EDIPI keys, and
--   maintains a Data Quality Quarantine & Remediation Audit Log.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS canonical;

-- 0. Data Quality & Entity Resolution Audit / Quarantine Table
CREATE TABLE IF NOT EXISTS canonical.dq_quarantine_log (
    dq_event_id             BIGSERIAL PRIMARY KEY,
    source_system           VARCHAR(32) NOT NULL,
    source_table            VARCHAR(64) NOT NULL,
    record_pk               VARCHAR(64) NOT NULL,
    rule_violated           VARCHAR(64) NOT NULL, -- UIC_FORMAT_DRIFT, DUPLICATE_CDC_ROW, ORPHAN_FOREIGN_KEY
    resolution_action       VARCHAR(32) NOT NULL, -- NORMALIZE_AND_HEAL, DEDUPLICATE, QUARANTINE_FK
    raw_value               TEXT,
    normalized_value        TEXT,
    detected_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 1. Canonical Unit Hierarchy (FMSWeb Master)
CREATE TABLE IF NOT EXISTS canonical.unit_hierarchy (
    uic                     CHAR(6) PRIMARY KEY CHECK (uic ~ '^[A-Z0-9]{6}$'),
    parent_uic              CHAR(6) REFERENCES canonical.unit_hierarchy(uic),
    unit_name               VARCHAR(160) NOT NULL,
    short_name              VARCHAR(32) NOT NULL,
    echelon                 VARCHAR(16) NOT NULL CHECK (echelon IN ('BDE', 'BN', 'CO')),
    unit_type               VARCHAR(32) NOT NULL,
    station_installation    VARCHAR(80) NOT NULL,
    cost_center             VARCHAR(32) NOT NULL,
    mtoe_doc_no             VARCHAR(32) NOT NULL,
    authorized_personnel    INTEGER NOT NULL CHECK (authorized_personnel >= 0),
    effective_fy            INTEGER NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_canonical_unit_parent ON canonical.unit_hierarchy(parent_uic);

-- 2. Canonical MTOE Billets & Equipment Authorizations
CREATE TABLE IF NOT EXISTS canonical.mtoe_billet (
    billet_id               VARCHAR(32) PRIMARY KEY,
    uic                     CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    para_no                 VARCHAR(8) NOT NULL,
    line_no                 VARCHAR(8) NOT NULL,
    position_title          VARCHAR(120) NOT NULL,
    mos_auth                VARCHAR(8) NOT NULL,
    grade_auth              VARCHAR(8) NOT NULL,
    auth_qty                INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS canonical.mtoe_equipment_authorization (
    mtoe_equip_auth_id      VARCHAR(40) PRIMARY KEY,
    uic                     CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    lin                     VARCHAR(12) NOT NULL,
    nsn                     VARCHAR(20) NOT NULL,
    tamcn                   VARCHAR(12) NOT NULL,
    nomenclature            VARCHAR(160) NOT NULL,
    erc_code                CHAR(1) NOT NULL CHECK (erc_code IN ('P', 'A', 'B')),
    authorized_qty          INTEGER NOT NULL CHECK (authorized_qty >= 0)
);

-- 3. Canonical Soldier Master (IPPS-A Resolved)
CREATE TABLE IF NOT EXISTS canonical.soldier_master (
    edipi_dod_id            CHAR(10) PRIMARY KEY CHECK (edipi_dod_id ~ '^[0-9]{10}$'),
    first_name              VARCHAR(64) NOT NULL,
    last_name               VARCHAR(64) NOT NULL,
    component               VARCHAR(32) NOT NULL,
    current_uic             CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    billet_id               VARCHAR(32) REFERENCES canonical.mtoe_billet(billet_id),
    pay_grade               VARCHAR(6) NOT NULL,
    rank_code               VARCHAR(8) NOT NULL,
    personnel_category      VARCHAR(16) NOT NULL CHECK (personnel_category IN ('ENLISTED', 'WARRANT', 'OFFICER')),
    primary_mos             VARCHAR(8) NOT NULL,
    security_clearance      VARCHAR(16) NOT NULL,
    deployable_flag         BOOLEAN NOT NULL,
    pulhes_profile          CHAR(6) NOT NULL,
    duty_status             VARCHAR(32) NOT NULL,
    last_acft_score         INTEGER CHECK (last_acft_score BETWEEN 0 AND 600),
    weapons_qual_level      VARCHAR(24),
    promotions_count        INTEGER NOT NULL DEFAULT 0,
    pcs_moves_count         INTEGER NOT NULL DEFAULT 0,
    valid_from              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_current              BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_canonical_soldier_uic ON canonical.soldier_master(current_uic);
CREATE INDEX IF NOT EXISTS idx_canonical_soldier_mos ON canonical.soldier_master(primary_mos);

-- 4. Canonical Soldier Assignment History (IPPS-A Longitudinal Slotting)
CREATE TABLE IF NOT EXISTS canonical.soldier_assignment_history (
    assignment_id           VARCHAR(32) PRIMARY KEY,
    edipi_dod_id            CHAR(10) NOT NULL REFERENCES canonical.soldier_master(edipi_dod_id),
    uic                     CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    billet_id               VARCHAR(32) REFERENCES canonical.mtoe_billet(billet_id),
    assignment_type         VARCHAR(40) NOT NULL,
    duty_status             VARCHAR(32) NOT NULL,
    pcs_order_no            VARCHAR(32) NOT NULL,
    effective_start_date    DATE NOT NULL,
    effective_end_date      DATE
);

-- 5. Canonical Serialized Equipment Master (GCSS-Army Property Book)
CREATE TABLE IF NOT EXISTS canonical.equipment_item_master (
    equipment_num           VARCHAR(32) PRIMARY KEY,
    serial_num              VARCHAR(32) NOT NULL UNIQUE,
    bumper_no               VARCHAR(24) NOT NULL,
    nsn                     VARCHAR(20) NOT NULL,
    lin                     VARCHAR(12) NOT NULL,
    tamcn                   VARCHAR(12) NOT NULL,
    nomenclature            VARCHAR(160) NOT NULL,
    equipment_category      VARCHAR(32) NOT NULL,
    erc_code                CHAR(1) NOT NULL CHECK (erc_code IN ('P', 'A', 'B')),
    owning_uic              CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    operational_status      VARCHAR(8) NOT NULL CHECK (operational_status IN ('FMC', 'NMCM', 'NMCS')),
    odometer_miles          NUMERIC(12, 2) NOT NULL DEFAULT 0,
    engine_hours            NUMERIC(12, 2) NOT NULL DEFAULT 0,
    replacement_cost_usd    NUMERIC(14, 2) NOT NULL,
    dispatch_cycles         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_canonical_equip_uic ON canonical.equipment_item_master(owning_uic);
CREATE INDEX IF NOT EXISTS idx_canonical_equip_status ON canonical.equipment_item_master(operational_status);

-- 6. Canonical Maintenance Work Orders (GCSS-Army 5988-E / 2404)
CREATE TABLE IF NOT EXISTS canonical.maintenance_work_order (
    work_order_id           VARCHAR(32) PRIMARY KEY,
    equipment_num           VARCHAR(32) NOT NULL REFERENCES canonical.equipment_item_master(equipment_num),
    owning_uic              CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    fault_code              VARCHAR(32) NOT NULL,
    fault_description       TEXT NOT NULL,
    maintenance_level       VARCHAR(32) NOT NULL,
    nmc_type                VARCHAR(8) NOT NULL CHECK (nmc_type IN ('NMCM', 'NMCS')),
    order_status            VARCHAR(32) NOT NULL,
    opened_ts               TIMESTAMPTZ NOT NULL,
    closed_ts               TIMESTAMPTZ,
    downtime_days           NUMERIC(8, 2),
    actual_man_hours        NUMERIC(8, 2) NOT NULL
);

-- 7. Canonical Class IX Parts Requisitions (MILSTRIP)
CREATE TABLE IF NOT EXISTS canonical.supply_requisition_milstrip (
    doc_number_milstrip     VARCHAR(24) PRIMARY KEY,
    work_order_id           VARCHAR(32) REFERENCES canonical.maintenance_work_order(work_order_id),
    equipment_num           VARCHAR(32) NOT NULL REFERENCES canonical.equipment_item_master(equipment_num),
    owning_uic              CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    part_nsn                VARCHAR(20) NOT NULL,
    part_nomenclature       VARCHAR(160) NOT NULL,
    qty_ordered             INTEGER NOT NULL CHECK (qty_ordered > 0),
    unit_price_usd          NUMERIC(14, 2) NOT NULL,
    extended_cost_usd       NUMERIC(14, 2) NOT NULL,
    priority_designator     CHAR(2) NOT NULL,
    supply_status_code      VARCHAR(32) NOT NULL,
    requisition_date        DATE NOT NULL
);

-- 8. Canonical Financial Obligations (GFEBS Integrated to MILSTRIP & Unit)
CREATE TABLE IF NOT EXISTS canonical.financial_obligation_gfebs (
    obligation_doc_no       VARCHAR(32) PRIMARY KEY,
    uic                     CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    cost_center             VARCHAR(32) NOT NULL,
    fund_code               VARCHAR(24) NOT NULL,
    element_of_resource     VARCHAR(40) NOT NULL,
    linked_milstrip_doc     VARCHAR(24) REFERENCES canonical.supply_requisition_milstrip(doc_number_milstrip),
    vendor_cage_code        VARCHAR(12) NOT NULL,
    obligated_amount_usd    NUMERIC(14, 2) NOT NULL,
    disbursed_amount_usd    NUMERIC(14, 2) NOT NULL,
    unliquidated_amount_usd NUMERIC(14, 2) GENERATED ALWAYS AS (obligated_amount_usd - disbursed_amount_usd) STORED,
    fiscal_year             INTEGER NOT NULL,
    posting_date            DATE NOT NULL
);

-- 9. Canonical Training & Monthly USR Readiness (DTMS / NetUSR)
CREATE TABLE IF NOT EXISTS canonical.training_event (
    event_id                VARCHAR(32) PRIMARY KEY,
    uic                     CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
    edipi_dod_id            CHAR(10) REFERENCES canonical.soldier_master(edipi_dod_id),
    training_type           VARCHAR(40) NOT NULL,
    metl_task_id            VARCHAR(24),
    raw_score               INTEGER NOT NULL,
    qualification_rating    VARCHAR(24) NOT NULL,
    event_date              DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical.unit_readiness_usr (
    usr_report_id           VARCHAR(32) PRIMARY KEY,
    uic                     CHAR(6) NOT NULL REFERENCES canonical.unit_hierarchy(uic),
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
    overall_c_rating        CHAR(3) NOT NULL CHECK (overall_c_rating IN ('C-1', 'C-2', 'C-3', 'C-4')),
    rearmm_phase            VARCHAR(24) NOT NULL,
    UNIQUE (uic, report_month)
);
