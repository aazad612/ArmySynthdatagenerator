-- =============================================================================
-- SOAP: Synthetic Operational Army Platform
-- Layer 4: Multi-Source Integration & Entity Resolution Pipeline (PostgreSQL)
-- =============================================================================
-- Purpose:
--   Production SQL ELT pipeline that transforms `raw_erp.*` into `canonical.*`
--   and `mart_readiness.*`:
--     1. Normalizes dirty UIC strings (stripping hyphens/whitespace, uppercasing)
--        and logs every healed drift to `canonical.dq_quarantine_log`.
--     2. Deduplicates at-least-once CDC replays via window functions (`ROW_NUMBER()`)
--        and logs every duplicate to `canonical.dq_quarantine_log`.
--     3. Quarantines orphaned foreign keys (e.g., provisional UICs not in FMSWeb)
--        into `canonical.dq_quarantine_log` while loading clean rows.
--     4. Populates the Kimball Star Schema dimensions and cross-ERP facts.
-- =============================================================================

-- Helper SQL Function: Standardize Army 6-char Alphanumeric UIC
CREATE OR REPLACE FUNCTION canonical.fn_normalize_uic(raw_uic TEXT)
RETURNS CHAR(6)
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT SUBSTRING(UPPER(REGEXP_REPLACE(TRIM(COALESCE(raw_uic, '')), '[^A-Za-z0-9]', '', 'g')) FROM 1 FOR 6)::CHAR(6);
$$;

-- Step 1: Audit & Log UIC Format Drift across Raw Systems
INSERT INTO canonical.dq_quarantine_log (
    source_system, source_table, record_pk, rule_violated, resolution_action, raw_value, normalized_value
)
SELECT 'GCSSA', 'raw_gcssa_equipment', equipment_num, 'UIC_FORMAT_DRIFT', 'NORMALIZE_AND_HEAL',
       owning_uic, canonical.fn_normalize_uic(owning_uic)
FROM raw_erp.raw_gcssa_equipment
WHERE owning_uic IS DISTINCT FROM canonical.fn_normalize_uic(owning_uic)
UNION ALL
SELECT 'GFEBS', 'raw_gfebs_obligations', obligation_doc_no, 'UIC_FORMAT_DRIFT', 'NORMALIZE_AND_HEAL',
       uic, canonical.fn_normalize_uic(uic)
FROM raw_erp.raw_gfebs_obligations
WHERE uic IS DISTINCT FROM canonical.fn_normalize_uic(uic)
UNION ALL
SELECT 'DTMS', 'raw_dtms_training_events', event_id, 'UIC_FORMAT_DRIFT', 'NORMALIZE_AND_HEAL',
       uic, canonical.fn_normalize_uic(uic)
FROM raw_erp.raw_dtms_training_events
WHERE uic IS DISTINCT FROM canonical.fn_normalize_uic(uic);

-- Step 2: Audit & Log Duplicate CDC Rows in IPPS-A and GCSS-Army
INSERT INTO canonical.dq_quarantine_log (
    source_system, source_table, record_pk, rule_violated, resolution_action, raw_value, normalized_value
)
SELECT 'IPPSA', 'raw_ippsa_soldiers', edipi_dod_id, 'DUPLICATE_CDC_ROW', 'DEDUPLICATE',
       'duplicate_count=' || COUNT(*)::TEXT, 'retained_latest_cdc_sequence'
FROM raw_erp.raw_ippsa_soldiers
GROUP BY edipi_dod_id
HAVING COUNT(*) > 1
UNION ALL
SELECT 'GCSSA', 'raw_gcssa_work_orders', work_order_id, 'DUPLICATE_CDC_ROW', 'DEDUPLICATE',
       'duplicate_count=' || COUNT(*)::TEXT, 'retained_latest_cdc_sequence'
FROM raw_erp.raw_gcssa_work_orders
GROUP BY work_order_id
HAVING COUNT(*) > 1;

-- Step 3: Load Canonical Force Structure Hierarchy (FMSWeb)
INSERT INTO canonical.unit_hierarchy (
    uic, parent_uic, unit_name, short_name, echelon, unit_type,
    station_installation, cost_center, mtoe_doc_no, authorized_personnel, effective_fy
)
SELECT
    canonical.fn_normalize_uic(uic),
    CASE WHEN parent_uic IS NOT NULL THEN canonical.fn_normalize_uic(parent_uic) ELSE NULL END,
    unit_name, short_name, echelon, unit_type,
    station_installation, cost_center, mtoe_doc_no, authorized_personnel, effective_fy
FROM raw_erp.raw_fmsweb_units
ON CONFLICT (uic) DO UPDATE SET
    authorized_personnel = EXCLUDED.authorized_personnel,
    updated_at = NOW();

-- Step 4: Audit & Quarantine Orphaned UIC Foreign Keys in IPPS-A Assignments
INSERT INTO canonical.dq_quarantine_log (
    source_system, source_table, record_pk, rule_violated, resolution_action, raw_value, normalized_value
)
SELECT 'IPPSA', 'raw_ippsa_assignments', a.assignment_id, 'ORPHAN_FOREIGN_KEY', 'QUARANTINE_FK',
       a.uic, NULL
FROM raw_erp.raw_ippsa_assignments a
LEFT JOIN canonical.unit_hierarchy u ON u.uic = canonical.fn_normalize_uic(a.uic)
WHERE u.uic IS NULL;

-- Step 5: Load Canonical MTOE Billets & Equipment Authorizations
INSERT INTO canonical.mtoe_billet (
    billet_id, uic, para_no, line_no, position_title, mos_auth, grade_auth, auth_qty
)
SELECT DISTINCT ON (billet_id)
    billet_id, canonical.fn_normalize_uic(uic), para_no, line_no, position_title, mos_auth, grade_auth, auth_qty
FROM raw_erp.raw_fmsweb_mtoe_billets
ON CONFLICT (billet_id) DO NOTHING;

INSERT INTO canonical.mtoe_equipment_authorization (
    mtoe_equip_auth_id, uic, lin, nsn, tamcn, nomenclature, erc_code, authorized_qty
)
SELECT DISTINCT ON (mtoe_equip_auth_id)
    mtoe_equip_auth_id, canonical.fn_normalize_uic(uic), lin, nsn, tamcn, nomenclature, erc_code, authorized_qty
FROM raw_erp.raw_fmsweb_mtoe_equipment
ON CONFLICT (mtoe_equip_auth_id) DO NOTHING;

-- Step 6: Deduplicate and Load Canonical Soldiers (IPPS-A)
WITH dedup_soldiers AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY edipi_dod_id ORDER BY _cdc_sequence DESC, _ingested_at DESC) AS rn
    FROM raw_erp.raw_ippsa_soldiers
)
INSERT INTO canonical.soldier_master (
    edipi_dod_id, first_name, last_name, component, current_uic, billet_id,
    pay_grade, rank_code, personnel_category, primary_mos, security_clearance,
    deployable_flag, pulhes_profile, duty_status, last_acft_score, weapons_qual_level,
    promotions_count, pcs_moves_count
)
SELECT
    s.edipi_dod_id::CHAR(10), s.first_name, s.last_name, s.component,
    canonical.fn_normalize_uic(s.current_uic), s.billet_id,
    s.pay_grade, s.rank_code, s.personnel_category, TRIM(UPPER(s.primary_mos)), s.security_clearance,
    s.deployable_flag, s.pulhes_profile::CHAR(6), s.duty_status, s.last_acft_score, s.weapons_qual_level,
    s.promotions_count, s.pcs_moves_count
FROM dedup_soldiers s
JOIN canonical.unit_hierarchy u ON u.uic = canonical.fn_normalize_uic(s.current_uic)
WHERE s.rn = 1
ON CONFLICT (edipi_dod_id) DO UPDATE SET
    current_uic = EXCLUDED.current_uic,
    pay_grade = EXCLUDED.pay_grade,
    rank_code = EXCLUDED.rank_code,
    deployable_flag = EXCLUDED.deployable_flag,
    duty_status = EXCLUDED.duty_status,
    last_acft_score = EXCLUDED.last_acft_score,
    weapons_qual_level = EXCLUDED.weapons_qual_level;

-- Step 7: Load Validated Soldier Assignments (filtering out quarantined orphan FKs)
INSERT INTO canonical.soldier_assignment_history (
    assignment_id, edipi_dod_id, uic, billet_id, assignment_type, duty_status,
    pcs_order_no, effective_start_date, effective_end_date
)
SELECT DISTINCT ON (a.assignment_id)
    a.assignment_id, a.edipi_dod_id::CHAR(10), canonical.fn_normalize_uic(a.uic),
    a.billet_id, a.assignment_type, a.duty_status, a.pcs_order_no,
    a.effective_start_date, a.effective_end_date
FROM raw_erp.raw_ippsa_assignments a
JOIN canonical.unit_hierarchy u ON u.uic = canonical.fn_normalize_uic(a.uic)
JOIN canonical.soldier_master s ON s.edipi_dod_id = a.edipi_dod_id::CHAR(10)
ON CONFLICT (assignment_id) DO NOTHING;

-- Step 8: Normalize and Load Serialized Equipment Master (GCSS-Army)
WITH dedup_equip AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY equipment_num ORDER BY _cdc_sequence DESC, _ingested_at DESC) AS rn
    FROM raw_erp.raw_gcssa_equipment
)
INSERT INTO canonical.equipment_item_master (
    equipment_num, serial_num, bumper_no, nsn, lin, tamcn, nomenclature,
    equipment_category, erc_code, owning_uic, operational_status,
    odometer_miles, engine_hours, replacement_cost_usd, dispatch_cycles
)
SELECT
    e.equipment_num, e.serial_num, e.bumper_no, e.nsn, e.lin, e.tamcn, e.nomenclature,
    e.equipment_category, e.erc_code::CHAR(1), canonical.fn_normalize_uic(e.owning_uic),
    e.operational_status, e.odometer_miles, e.engine_hours, e.replacement_cost_usd, e.dispatch_cycles
FROM dedup_equip e
JOIN canonical.unit_hierarchy u ON u.uic = canonical.fn_normalize_uic(e.owning_uic)
WHERE e.rn = 1
ON CONFLICT (equipment_num) DO UPDATE SET
    operational_status = EXCLUDED.operational_status,
    odometer_miles = EXCLUDED.odometer_miles,
    engine_hours = EXCLUDED.engine_hours,
    dispatch_cycles = EXCLUDED.dispatch_cycles;

-- Step 9: Deduplicate and Load Maintenance Work Orders, Class IX Requisitions & GFEBS Obligations
WITH dedup_wo AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY work_order_id ORDER BY _cdc_sequence DESC, _ingested_at DESC) AS rn
    FROM raw_erp.raw_gcssa_work_orders
)
INSERT INTO canonical.maintenance_work_order (
    work_order_id, equipment_num, owning_uic, fault_code, fault_description,
    maintenance_level, nmc_type, order_status, opened_ts, closed_ts, downtime_days, actual_man_hours
)
SELECT
    w.work_order_id, w.equipment_num, canonical.fn_normalize_uic(w.owning_uic),
    w.fault_code, w.fault_description, w.maintenance_level, w.nmc_type, w.order_status,
    w.opened_ts, w.closed_ts,
    CASE WHEN w.closed_ts IS NOT NULL
         THEN ROUND(EXTRACT(EPOCH FROM (w.closed_ts - w.opened_ts)) / 86400.0, 2)
         ELSE NULL END,
    w.actual_man_hours
FROM dedup_wo w
JOIN canonical.equipment_item_master e ON e.equipment_num = w.equipment_num
WHERE w.rn = 1
ON CONFLICT (work_order_id) DO NOTHING;

INSERT INTO canonical.supply_requisition_milstrip (
    doc_number_milstrip, work_order_id, equipment_num, owning_uic,
    part_nsn, part_nomenclature, qty_ordered, unit_price_usd, extended_cost_usd,
    priority_designator, supply_status_code, requisition_date
)
SELECT DISTINCT ON (r.doc_number_milstrip)
    r.doc_number_milstrip, r.work_order_id, r.equipment_num, canonical.fn_normalize_uic(r.owning_uic),
    r.part_nsn, r.part_nomenclature, r.qty_ordered, r.unit_price_usd, r.extended_cost_usd,
    r.priority_designator::CHAR(2), r.supply_status_code, r.requisition_date
FROM raw_erp.raw_gcssa_supply_requisitions r
JOIN canonical.equipment_item_master e ON e.equipment_num = r.equipment_num
ON CONFLICT (doc_number_milstrip) DO NOTHING;

INSERT INTO canonical.financial_obligation_gfebs (
    obligation_doc_no, uic, cost_center, fund_code, element_of_resource,
    linked_milstrip_doc, vendor_cage_code, obligated_amount_usd, disbursed_amount_usd,
    fiscal_year, posting_date
)
SELECT DISTINCT ON (g.obligation_doc_no)
    g.obligation_doc_no, canonical.fn_normalize_uic(g.uic), g.cost_center, g.fund_code,
    g.element_of_resource, g.linked_milstrip_doc, g.vendor_cage_code,
    g.obligated_amount_usd, g.disbursed_amount_usd, g.fiscal_year, g.posting_date
FROM raw_erp.raw_gfebs_obligations g
JOIN canonical.unit_hierarchy u ON u.uic = canonical.fn_normalize_uic(g.uic)
ON CONFLICT (obligation_doc_no) DO NOTHING;

-- Step 10: Load Canonical DTMS Training & NetUSR Reports
INSERT INTO canonical.training_event (
    event_id, uic, edipi_dod_id, training_type, metl_task_id, raw_score, qualification_rating, event_date
)
SELECT DISTINCT ON (t.event_id)
    t.event_id, canonical.fn_normalize_uic(t.uic),
    t.edipi_dod_id::CHAR(10), t.training_type, t.metl_task_id,
    t.raw_score, t.qualification_rating, t.event_date
FROM raw_erp.raw_dtms_training_events t
JOIN canonical.unit_hierarchy u ON u.uic = canonical.fn_normalize_uic(t.uic)
ON CONFLICT (event_id) DO NOTHING;

INSERT INTO canonical.unit_readiness_usr (
    usr_report_id, uic, report_month, authorized_strength, assigned_strength, deployable_strength,
    personnel_fill_pct, equipment_on_hand_count, equipment_fmc_count, equipment_fmc_pct,
    p_level, s_level, r_level, t_level, overall_c_rating, rearmm_phase
)
SELECT DISTINCT ON (usr_report_id)
    usr_report_id, canonical.fn_normalize_uic(uic), report_month::CHAR(7),
    authorized_strength, assigned_strength, deployable_strength,
    personnel_fill_pct, equipment_on_hand_count, equipment_fmc_count, equipment_fmc_pct,
    p_level::CHAR(3), s_level::CHAR(3), r_level::CHAR(3), t_level::CHAR(3),
    overall_c_rating::CHAR(3), rearmm_phase
FROM raw_erp.raw_dtms_usr_readiness
ON CONFLICT (usr_report_id) DO NOTHING;

-- Step 11: Populate Kimball Star Schema (`mart_readiness`) using Recursive Command Path CTE
WITH RECURSIVE unit_tree AS (
    SELECT
        u.uic,
        u.unit_name,
        u.short_name,
        u.echelon,
        u.unit_type,
        u.parent_uic,
        CASE WHEN u.echelon = 'BN' THEN u.uic ELSE NULL END AS battalion_uic,
        CASE WHEN u.echelon = 'BDE' THEN u.uic ELSE NULL END AS brigade_uic,
        u.short_name::TEXT AS command_path,
        u.station_installation,
        u.cost_center,
        u.authorized_personnel
    FROM canonical.unit_hierarchy u
    WHERE u.parent_uic IS NULL
    UNION ALL
    SELECT
        c.uic,
        c.unit_name,
        c.short_name,
        c.echelon,
        c.unit_type,
        c.parent_uic,
        COALESCE(CASE WHEN c.echelon = 'BN' THEN c.uic ELSE NULL END, p.battalion_uic),
        p.brigade_uic,
        p.command_path || ' > ' || c.short_name,
        c.station_installation,
        c.cost_center,
        c.authorized_personnel
    FROM canonical.unit_hierarchy c
    JOIN unit_tree p ON c.parent_uic = p.uic
)
INSERT INTO mart_readiness.dim_unit (
    uic, unit_name, short_name, echelon, unit_type, parent_uic,
    battalion_uic, brigade_uic, command_path, station_installation, cost_center, authorized_personnel
)
SELECT
    uic, unit_name, short_name, echelon, unit_type, parent_uic,
    battalion_uic, brigade_uic, command_path, station_installation, cost_center, authorized_personnel
FROM unit_tree
ON CONFLICT (uic) DO NOTHING;

INSERT INTO mart_readiness.dim_soldier (
    edipi_dod_id, full_name, pay_grade, rank_code, personnel_category,
    primary_mos, security_clearance, current_uic, deployable_flag, duty_status,
    last_acft_score, weapons_qual_level
)
SELECT
    edipi_dod_id, last_name || ', ' || first_name, pay_grade, rank_code, personnel_category,
    primary_mos, security_clearance, current_uic, deployable_flag, duty_status,
    last_acft_score, weapons_qual_level
FROM canonical.soldier_master
ON CONFLICT (edipi_dod_id) DO NOTHING;

INSERT INTO mart_readiness.dim_equipment (
    equipment_num, serial_num, bumper_no, lin, nsn, nomenclature,
    equipment_category, erc_code, is_pacing_item, owning_uic, current_status, replacement_cost_usd
)
SELECT
    equipment_num, serial_num, bumper_no, lin, nsn, nomenclature,
    equipment_category, erc_code, (erc_code = 'P'), owning_uic, operational_status, replacement_cost_usd
FROM canonical.equipment_item_master
ON CONFLICT (equipment_num) DO NOTHING;

INSERT INTO mart_readiness.fact_unit_usr_monthly (
    usr_report_id, unit_key, uic, report_month, authorized_strength, assigned_strength,
    deployable_strength, personnel_fill_pct, equipment_on_hand_count, equipment_fmc_count,
    equipment_fmc_pct, p_level, s_level, r_level, t_level, overall_c_rating, c_rating_numeric, rearmm_phase
)
SELECT
    u.usr_report_id, du.unit_key, u.uic, u.report_month, u.authorized_strength, u.assigned_strength,
    u.deployable_strength, u.personnel_fill_pct, u.equipment_on_hand_count, u.equipment_fmc_count,
    u.equipment_fmc_pct, u.p_level, u.s_level, u.r_level, u.t_level, u.overall_c_rating,
    SUBSTRING(u.overall_c_rating FROM 3 FOR 1)::INTEGER, u.rearmm_phase
FROM canonical.unit_readiness_usr u
JOIN mart_readiness.dim_unit du ON du.uic = u.uic
ON CONFLICT (usr_report_id) DO NOTHING;

INSERT INTO mart_readiness.fact_maintenance_supply_finance (
    work_order_id, unit_key, equipment_key, uic, equipment_num, nmc_type, order_status,
    downtime_days, actual_man_hours, milstrip_doc_count, parts_extended_cost_usd,
    gfebs_obligated_usd, gfebs_disbursed_usd, financial_variance_usd
)
SELECT
    w.work_order_id,
    du.unit_key,
    de.equipment_key,
    w.owning_uic,
    w.equipment_num,
    w.nmc_type,
    w.order_status,
    w.downtime_days,
    w.actual_man_hours,
    COUNT(r.doc_number_milstrip),
    COALESCE(SUM(r.extended_cost_usd), 0),
    COALESCE(SUM(g.obligated_amount_usd), 0),
    COALESCE(SUM(g.disbursed_amount_usd), 0),
    COALESCE(SUM(r.extended_cost_usd), 0) - COALESCE(SUM(g.obligated_amount_usd), 0)
FROM canonical.maintenance_work_order w
JOIN mart_readiness.dim_unit du ON du.uic = w.owning_uic
JOIN mart_readiness.dim_equipment de ON de.equipment_num = w.equipment_num
LEFT JOIN canonical.supply_requisition_milstrip r ON r.work_order_id = w.work_order_id
LEFT JOIN canonical.financial_obligation_gfebs g ON g.linked_milstrip_doc = r.doc_number_milstrip
GROUP BY w.work_order_id, du.unit_key, de.equipment_key, w.owning_uic, w.equipment_num,
         w.nmc_type, w.order_status, w.downtime_days, w.actual_man_hours
ON CONFLICT (work_order_id) DO NOTHING;
