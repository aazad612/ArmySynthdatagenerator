"""
Multi-Source U.S. Army Operational World Simulator.

Executes time-stepped declarative state machines for Units (FMSWeb/NetUSR),
Soldiers (IPPS-A/DTMS), and Serialized Equipment (GCSS-Army/GFEBS), maintaining
causal and referential integrity across all 5 enterprise source systems while
optionally injecting realistic source-system CDC/integration anomalies.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from soap.engine.state_machine import EntityContext, ModuleRegistry, SimulationEvent, StateMachineRunner
from soap.reference.army_catalog import (
    ARMY_EQUIPMENT_LINS,
    ARMY_MOS_LIST,
    ARMY_RANKS,
    ARMY_UNITS,
    FIRST_NAMES,
    LIN_BY_CODE,
    NEXT_PROMOTION_GRADE,
    PARTS_BY_LIN,
    RANK_BY_GRADE,
    SURNAMES,
    UNIT_BY_UIC,
    UNIT_MTOE_EQUIPMENT_AUTH,
)


@dataclass
class SimulationConfig:
    seed: int = 42
    start_date: date = date(2026, 1, 1)
    days: int = 180
    tick_days: int = 1
    scale_factor: float = 0.25  # 0.25 = ~165 soldiers & ~250 equipment items; 1.0 = full brigade slice
    messiness_rate: float = 0.05  # Injects realistic CDC duplicates, UIC formatting drift & nulls


@dataclass
class SimulationOutput:
    config: SimulationConfig
    tables: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    raw_cdc_stream: List[Dict[str, Any]] = field(default_factory=list)
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


class ArmyWorldSimulator:
    """
    Runs the Synthea-architected U.S. Army operational simulation across:
      1. FMSWeb (Force Management System - MTOE & Hierarchy)
      2. IPPS-A (Integrated Personnel & Pay System - Army)
      3. GCSS-Army (Global Combat Support System - Army Maintenance & Supply)
      4. DTMS / NetUSR (Training & Monthly Unit Status Readiness)
      5. GFEBS (General Fund Enterprise Business System Financials)
    """

    def __init__(self, config: Optional[SimulationConfig] = None) -> None:
        self.config = config or SimulationConfig()
        self.rng = random.Random(self.config.seed)
        self.registry = ModuleRegistry()
        self.runner = StateMachineRunner(self.registry, self.rng)

        # Entity context registries
        self.unit_entities: Dict[str, EntityContext] = {}
        self.soldier_entities: Dict[str, EntityContext] = {}
        self.equipment_entities: Dict[str, EntityContext] = {}

        # Active work order tracking (equipment_number -> open work order dict)
        self._active_work_orders: Dict[str, Dict[str, Any]] = {}
        self._wo_seq = 100000
        self._req_seq = 1000
        self._gfebs_seq = 500000
        self._dtms_seq = 200000
        self._usr_seq = 10000
        self._ippsa_act_seq = 300000

        # Output relational tables (Silver-ready ground truth + Raw Bronze tables)
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "fmsweb_unit_hierarchy": [],
            "fmsweb_mtoe_billets": [],
            "fmsweb_mtoe_equipment": [],
            "ippsa_soldier_master": [],
            "ippsa_personnel_actions": [],
            "gcssa_equipment_master": [],
            "gcssa_work_orders": [],
            "gcssa_supply_requisitions": [],
            "dtms_individual_training": [],
            "netusr_unit_status_reports": [],
            "gfebs_financial_ledger": [],
        }
        self.raw_cdc_stream: List[Dict[str, Any]] = []

    def run(self) -> SimulationOutput:
        """Executes the full time-stepped simulation from start_date through start_date + days."""
        self._initialize_force_structure()
        self._initialize_personnel_cohort()
        self._initialize_equipment_fleet()

        current_date = self.config.start_date
        end_date = self.config.start_date + timedelta(days=self.config.days)

        while current_date <= end_date:
            # 1. Step Units
            for uic, u_ctx in self.unit_entities.items():
                events = self.runner.step_entity(u_ctx, current_date)
                for ev in events:
                    self._handle_domain_event(ev, current_date)

            # 2. Step Soldiers
            for dodid, s_ctx in self.soldier_entities.items():
                events = self.runner.step_entity(s_ctx, current_date)
                for ev in events:
                    self._handle_domain_event(ev, current_date)

            # 3. Step Equipment
            for eq_num, e_ctx in self.equipment_entities.items():
                events = self.runner.step_entity(e_ctx, current_date)
                for ev in events:
                    self._handle_domain_event(ev, current_date)

            current_date += timedelta(days=self.config.tick_days)

        # Snapshot final master records and state transition audit history
        self._finalize_master_tables(end_date)
        state_history = self._collect_state_history()

        # Inject controlled raw/Bronze CDC anomalies for Data Engineering pipeline testing
        self._generate_raw_cdc_stream()

        metrics = {
            "simulation_start_date": self.config.start_date.isoformat(),
            "simulation_end_date": end_date.isoformat(),
            "total_days": self.config.days,
            "seed": self.config.seed,
            "units_count": len(self.tables["fmsweb_unit_hierarchy"]),
            "mtoe_billets_count": len(self.tables["fmsweb_mtoe_billets"]),
            "soldiers_count": len(self.tables["ippsa_soldier_master"]),
            "personnel_actions_count": len(self.tables["ippsa_personnel_actions"]),
            "equipment_count": len(self.tables["gcssa_equipment_master"]),
            "work_orders_count": len(self.tables["gcssa_work_orders"]),
            "supply_requisitions_count": len(self.tables["gcssa_supply_requisitions"]),
            "training_events_count": len(self.tables["dtms_individual_training"]),
            "usr_reports_count": len(self.tables["netusr_unit_status_reports"]),
            "gfebs_postings_count": len(self.tables["gfebs_financial_ledger"]),
            "state_transitions_count": len(state_history),
            "raw_cdc_events_count": len(self.raw_cdc_stream),
        }

        return SimulationOutput(
            config=self.config,
            tables=self.tables,
            raw_cdc_stream=self.raw_cdc_stream,
            state_history=state_history,
            metrics=metrics,
        )

    def _initialize_force_structure(self) -> None:
        """Initializes FMSWeb Unit Hierarchy, MTOE Billets, and MTOE Equipment Authorizations."""
        for unit in ARMY_UNITS:
            scaled_auth = max(6, int(round(unit.auth_personnel * self.config.scale_factor)))
            self.tables["fmsweb_unit_hierarchy"].append(
                {
                    "uic": unit.uic,
                    "parent_uic": unit.parent_uic,
                    "unit_name": unit.unit_name,
                    "echelon": unit.echelon,
                    "unit_type": unit.unit_type,
                    "home_station": unit.home_station,
                    "dodaac": unit.dodaac,
                    "fund_center": unit.fund_center,
                    "authorized_strength": scaled_auth,
                    "effective_fy": 2026,
                }
            )

            # Create Unit FSM EntityContext
            self.unit_entities[unit.uic] = EntityContext(
                entity_id=unit.uic,
                entity_type="UNIT",
                attributes={
                    "uic": unit.uic,
                    "unit_name": unit.unit_name,
                    "echelon": unit.echelon,
                    "authorized_strength": scaled_auth,
                    "metl_t_score": self.rng.randint(72, 88),
                },
                active_module="unit_readiness_lifecycle",
            )

            # Generate MTOE Billets for the unit
            for seq in range(1, scaled_auth + 1):
                para_no = f"{(seq - 1) // 10 + 1:02d}"
                line_no = f"{(seq - 1) % 10 + 1:02d}"
                billet_id = f"{unit.uic}-{para_no}-{line_no}-{seq:03d}"
                grade, mos = self._sample_billet_grade_and_mos(unit.unit_type, seq)
                self.tables["fmsweb_mtoe_billets"].append(
                    {
                        "billet_id": billet_id,
                        "uic": unit.uic,
                        "para_no": para_no,
                        "line_no": line_no,
                        "position_title": f"{mos} {grade} Duty Position",
                        "auth_pay_grade": grade,
                        "auth_mos": mos,
                        "security_clearance_req": "TOP_SECRET" if mos in ("35F", "25B") or grade.startswith("O-") else "SECRET",
                    }
                )

            # Generate MTOE Equipment Authorizations for the unit
            eq_auth_map = UNIT_MTOE_EQUIPMENT_AUTH.get(unit.uic, {})
            for lin_code, base_qty in eq_auth_map.items():
                lin_def = LIN_BY_CODE[lin_code]
                scaled_qty = max(1, int(round(base_qty * self.config.scale_factor)))
                self.tables["fmsweb_mtoe_equipment"].append(
                    {
                        "uic": unit.uic,
                        "lin": lin_code,
                        "niin": lin_def.niin,
                        "nsn": lin_def.nsn,
                        "nomenclature": lin_def.nomenclature,
                        "equipment_category": lin_def.equipment_category,
                        "erc_code": lin_def.erc,
                        "authorized_qty": scaled_qty,
                    }
                )

    def _sample_billet_grade_and_mos(self, unit_type: str, seq: int) -> tuple[str, str]:
        if seq == 1:
            return ("O-3", "19K" if "ARMOR" in unit_type else "11B")
        if seq == 2:
            return ("E-8", "19K" if "ARMOR" in unit_type else "11B")
        grades = ["E-2", "E-3", "E-4", "E-4", "E-4", "E-5", "E-5", "E-6", "E-7", "O-1", "O-2", "W-2"]
        grade = self.rng.choice(grades)

        if "ARMOR" in unit_type:
            mos_pool = ["19K", "19K", "19K", "91A", "92A", "25B"]
        elif "MECH_INF" in unit_type or "COMBINED_ARMS" in unit_type:
            mos_pool = ["11B", "11B", "19K", "91M", "91B", "25B", "35F", "42A"]
        elif "FA_BN" in unit_type:
            mos_pool = ["13B", "13B", "91B", "92A", "25B", "88M"]
        elif "BSB" in unit_type:
            mos_pool = ["91A", "91B", "91M", "92A", "88M", "42A"]
        else:
            mos_pool = [m.mos_code for m in ARMY_MOS_LIST]
        return grade, self.rng.choice(mos_pool)

    def _initialize_personnel_cohort(self) -> None:
        """Populates ~92% of authorized MTOE billets with Soldiers in IPPS-A."""
        dodid_counter = 1400500100
        for billet in self.tables["fmsweb_mtoe_billets"]:
            # ~92% manning fill rate to produce realistic P-level variations
            if self.rng.random() > 0.92:
                continue

            dodid_counter += 7
            dodid = str(dodid_counter)
            first_name = self.rng.choice(FIRST_NAMES)
            last_name = self.rng.choice(SURNAMES)
            pay_grade = billet["auth_pay_grade"]
            rank_def = RANK_BY_GRADE[pay_grade]
            mos = billet["auth_mos"]

            tis_months = max(rank_def.min_tis_months, rank_def.min_tis_months + self.rng.randint(2, 36))
            tig_months = max(1, self.rng.randint(4, 28))
            months_to_ets = self.rng.randint(2, 48)
            pebd_date = self.config.start_date - timedelta(days=tis_months * 30)
            ets_date = self.config.start_date + timedelta(days=months_to_ets * 30)

            ssn_hash = hashlib.sha256(f"SSN-{dodid}".encode("utf-8")).hexdigest()[:16]

            attrs = {
                "dodid": dodid,
                "ssn_hash": ssn_hash,
                "first_name": first_name,
                "last_name": last_name,
                "pay_grade": pay_grade,
                "rank_code": rank_def.rank_code,
                "mos": mos,
                "assigned_uic": billet["uic"],
                "billet_id": billet["billet_id"],
                "duty_status": "PRESENT_FOR_DUTY",
                "deployable_flag": True,
                "security_clearance": billet["security_clearance_req"],
                "tis_months": tis_months,
                "tig_months": tig_months,
                "months_to_ets": months_to_ets,
                "pebd_date": pebd_date.isoformat(),
                "ets_date": ets_date.isoformat(),
                "promotion_eligible": NEXT_PROMOTION_GRADE.get(pay_grade) is not None,
            }

            self.soldier_entities[dodid] = EntityContext(
                entity_id=dodid,
                entity_type="SOLDIER",
                attributes=attrs,
                active_module="personnel_lifecycle",
            )

    def _initialize_equipment_fleet(self) -> None:
        """Populates serialized equipment in GCSS-Army matching FMSWeb MTOE authorizations."""
        eq_seq = 10500000
        for mtoe_eq in self.tables["fmsweb_mtoe_equipment"]:
            uic = mtoe_eq["uic"]
            lin_code = mtoe_eq["lin"]
            lin_def = LIN_BY_CODE[lin_code]
            unit_def = UNIT_BY_UIC[uic]
            auth_qty = mtoe_eq["authorized_qty"]

            # On-hand fill rate ~95% of MTOE authorization
            on_hand_qty = max(1, int(round(auth_qty * self.rng.uniform(0.90, 1.0))))
            for idx in range(1, on_hand_qty + 1):
                eq_seq += 1
                equipment_number = f"EQ{eq_seq}"
                serial_number = f"SN-{lin_code}-{uic[-3:]}-{idx:03d}"
                bumper_number = f"{uic[-2:]}-{lin_code[:2]}{idx:02d}"
                initial_hours = self.rng.randint(20, 290)

                attrs = {
                    "equipment_number": equipment_number,
                    "serial_number": serial_number,
                    "bumper_number": bumper_number,
                    "owning_uic": uic,
                    "dodaac": unit_def.dodaac,
                    "lin": lin_code,
                    "niin": lin_def.niin,
                    "nsn": lin_def.nsn,
                    "nomenclature": lin_def.nomenclature,
                    "erc_code": lin_def.erc,
                    "materiel_status": "FMC",
                    "operating_hours": initial_hours,
                    "acquisition_cost": lin_def.unit_replacement_cost,
                    "maintenance_mos": lin_def.maintenance_mos,
                }

                self.equipment_entities[equipment_number] = EntityContext(
                    entity_id=equipment_number,
                    entity_type="EQUIPMENT",
                    attributes=attrs,
                    active_module="equipment_lifecycle",
                )

    def _handle_domain_event(self, ev: SimulationEvent, current_date: date) -> None:
        """Translates state-machine emitted events into relational source-system records."""
        if ev.source_system == "IPPSA":
            self._handle_ippsa_event(ev, current_date)
        elif ev.source_system == "GCSS_ARMY":
            self._handle_gcssa_event(ev, current_date)
        elif ev.source_system == "DTMS_USR":
            self._handle_dtms_usr_event(ev, current_date)
        elif ev.source_system == "GFEBS":
            self._handle_gfebs_event(ev, current_date)

    def _handle_ippsa_event(self, ev: SimulationEvent, current_date: date) -> None:
        s_ctx = self.soldier_entities[ev.entity_id]
        attrs = s_ctx.attributes
        self._ippsa_act_seq += 1
        action_id = f"IPPSA-ACT-{self._ippsa_act_seq}"

        from_uic = attrs["assigned_uic"]
        to_uic = from_uic
        from_grade = attrs["pay_grade"]
        to_grade = from_grade

        if ev.event_type == "PROMOTION_ORDER":
            next_grade = NEXT_PROMOTION_GRADE.get(from_grade)
            if next_grade:
                to_grade = next_grade
                attrs["pay_grade"] = next_grade
                attrs["rank_code"] = RANK_BY_GRADE[next_grade].rank_code
                attrs["promotion_eligible"] = NEXT_PROMOTION_GRADE.get(next_grade) is not None

        elif ev.event_type == "PCS_TRANSFER_ORDER":
            candidate_uics = [u.uic for u in ARMY_UNITS if u.uic != from_uic]
            to_uic = self.rng.choice(candidate_uics)
            attrs["assigned_uic"] = to_uic

        elif ev.event_type == "ETS_SEPARATION":
            attrs["duty_status"] = "SEPARATED_ETS"
            attrs["deployable_flag"] = False

        self.tables["ippsa_personnel_actions"].append(
            {
                "action_id": action_id,
                "dodid": attrs["dodid"],
                "effective_date": current_date.isoformat(),
                "action_type": ev.event_type,
                "from_uic": from_uic,
                "to_uic": to_uic,
                "from_grade": from_grade,
                "to_grade": to_grade,
                "deployable_after_action": bool(attrs["deployable_flag"]),
                "source_state": ev.state_name,
            }
        )

    def _handle_gcssa_event(self, ev: SimulationEvent, current_date: date) -> None:
        e_ctx = self.equipment_entities[ev.entity_id]
        attrs = e_ctx.attributes
        eq_num = attrs["equipment_number"]
        uic = attrs["owning_uic"]
        lin_code = attrs["lin"]

        if ev.event_type == "WORK_ORDER_OPEN":
            self._wo_seq += 1
            wo_id = f"WO-{self._wo_seq}"
            parts = PARTS_BY_LIN.get(lin_code, [])
            part = self.rng.choice(parts) if parts else None
            maintainer_dodid = self._find_maintainer_dodid(uic, attrs["maintenance_mos"])

            wo_record = {
                "work_order_id": wo_id,
                "equipment_number": eq_num,
                "serial_number": attrs["serial_number"],
                "owning_uic": uic,
                "lin": lin_code,
                "order_type": ev.payload.get("order_type", "ZM01_CORRECTIVE_DEADLINE"),
                "fault_description": f"Deadlining fault on {part.nomenclature if part else attrs['nomenclature']}",
                "maintenance_level": "FIELD_30_level",
                "maintainer_dodid": maintainer_dodid,
                "opened_date": current_date.isoformat(),
                "closed_date": None,
                "turnaround_days": None,
                "order_status": "OPEN_NMCS",
                "labor_hours": round(self.rng.uniform(6.0, 32.0), 1),
                "_selected_part": part,
            }
            self._active_work_orders[eq_num] = wo_record
            self.tables["gcssa_work_orders"].append(wo_record)

        elif ev.event_type == "CLASS_IX_REQUISITION":
            wo_record = self._active_work_orders.get(eq_num)
            if not wo_record:
                return
            part = wo_record.get("_selected_part")
            if not part:
                return
            self._req_seq += 1
            julian = f"{current_date.year % 10}{current_date.timetuple().tm_yday:03d}"
            dodaac = attrs["dodaac"]
            req_doc_num = f"{dodaac}{julian}{self._req_seq % 10000:04d}"
            qty = 1
            ext_amount = round(part.unit_price * qty, 2)

            req_record = {
                "requisition_doc_num": req_doc_num,
                "work_order_id": wo_record["work_order_id"],
                "equipment_number": eq_num,
                "owning_uic": uic,
                "dodaac": dodaac,
                "niin": part.niin,
                "nsn": part.nsn,
                "part_nomenclature": part.nomenclature,
                "supply_class": "IX",
                "quantity_ordered": qty,
                "unit_price": part.unit_price,
                "extended_amount": ext_amount,
                "priority_designator": "02",
                "order_date": current_date.isoformat(),
                "receipt_date": None,
                "requisition_status": "BACKORDERED_NMCS",
            }
            wo_record["_active_req"] = req_record
            self.tables["gcssa_supply_requisitions"].append(req_record)

        elif ev.event_type == "WORK_ORDER_CLOSE":
            wo_record = self._active_work_orders.pop(eq_num, None)
            if wo_record:
                opened_dt = date.fromisoformat(wo_record["opened_date"])
                wo_record["closed_date"] = current_date.isoformat()
                wo_record["turnaround_days"] = (current_date - opened_dt).days
                wo_record["order_status"] = "TECO_CLOSED"
                req_record = wo_record.get("_active_req")
                if req_record:
                    req_record["receipt_date"] = (current_date - timedelta(days=2)).isoformat()
                    req_record["requisition_status"] = "RECEIVED_ISSUED"

    def _find_maintainer_dodid(self, uic: str, preferred_mos: str) -> Optional[str]:
        candidates = [
            s.entity_id
            for s in self.soldier_entities.values()
            if s.attributes.get("mos") in (preferred_mos, "91A", "91B", "91M")
            and not s.is_terminated
        ]
        if candidates:
            return self.rng.choice(candidates)
        return None

    def _handle_gfebs_event(self, ev: SimulationEvent, current_date: date) -> None:
        e_ctx = self.equipment_entities[ev.entity_id]
        attrs = e_ctx.attributes
        eq_num = attrs["equipment_number"]
        uic = attrs["owning_uic"]
        unit_def = UNIT_BY_UIC[uic]

        # Lookup requisition amount from active or most recent work order
        req_doc = None
        amount = round(self.rng.uniform(1200.0, 28000.0), 2)
        for req in reversed(self.tables["gcssa_supply_requisitions"]):
            if req["equipment_number"] == eq_num:
                req_doc = req["requisition_doc_num"]
                amount = req["extended_amount"]
                break

        self._gfebs_seq += 1
        doc_num = f"GFEBS-{current_date.year}-{self._gfebs_seq}"
        self.tables["gfebs_financial_ledger"].append(
            {
                "document_number": doc_num,
                "fiscal_year": current_date.year,
                "posting_date": current_date.isoformat(),
                "fund_center": unit_def.fund_center,
                "uic": uic,
                "appropriation_code": "2020_OMA",
                "cost_element": "2600.00_CLASS_IX_PARTS",
                "commitment_item": "260100",
                "posting_type": ev.payload.get("posting_type", "OBLIGATION"),
                "reference_doc_id": req_doc or eq_num,
                "amount_usd": amount,
            }
        )

    def _handle_dtms_usr_event(self, ev: SimulationEvent, current_date: date) -> None:
        if ev.entity_type == "SOLDIER":
            s_ctx = self.soldier_entities[ev.entity_id]
            attrs = s_ctx.attributes
            self._dtms_seq += 1
            score = self.rng.randint(23, 40)
            if score >= 36:
                qual = "EXPERT"
            elif score >= 30:
                qual = "SHARPSHOOTER"
            else:
                qual = "MARKSMAN"

            self.tables["dtms_individual_training"].append(
                {
                    "training_record_id": f"DTMS-{self._dtms_seq}",
                    "dodid": attrs["dodid"],
                    "uic": attrs["assigned_uic"],
                    "event_date": current_date.isoformat(),
                    "event_category": ev.event_type,
                    "weapon_or_course": ev.payload.get(
                        "weapon_system", ev.payload.get("training_center", "M4A1_CARBINE")
                    ),
                    "score": score,
                    "qualification_rating": qual,
                    "go_no_go": "GO",
                }
            )

        elif ev.entity_type == "UNIT" and ev.event_type == "MONTHLY_NETUSR_SUBMISSION":
            uic = ev.entity_id
            u_ctx = self.unit_entities[uic]
            unit_def = UNIT_BY_UIC[uic]
            auth_p = u_ctx.attributes["authorized_strength"]

            assigned_soldiers = [
                s
                for s in self.soldier_entities.values()
                if s.attributes["assigned_uic"] == uic and not s.is_terminated
            ]
            assigned_p = len(assigned_soldiers)
            avail_p = sum(1 for s in assigned_soldiers if s.attributes.get("deployable_flag", True))
            p_fill_pct = round((avail_p / max(1, auth_p)) * 100.0, 1)
            p_level = self._score_to_rating(p_fill_pct, (90.0, 80.0, 70.0))

            unit_eq = [
                e for e in self.equipment_entities.values() if e.attributes["owning_uic"] == uic
            ]
            pacing_eq = [e for e in unit_eq if e.attributes["erc_code"] == "P"] or unit_eq
            total_eq = len(pacing_eq)
            fmc_eq = sum(1 for e in pacing_eq if e.attributes["materiel_status"] == "FMC")

            s_onhand_pct = round(min(100.0, (len(unit_eq) / max(1, len(unit_eq))) * 96.0), 1)
            s_level = self._score_to_rating(s_onhand_pct, (90.0, 80.0, 70.0))

            r_fmc_pct = round((fmc_eq / max(1, total_eq)) * 100.0, 1)
            r_level = self._score_to_rating(r_fmc_pct, (90.0, 80.0, 70.0))

            t_pct = float(min(99, u_ctx.attributes.get("metl_t_score", 80)))
            t_level = self._score_to_rating(t_pct, (85.0, 75.0, 65.0))

            # Overall C-rating is the worst of P, S, R, T (AR 220-1 rule)
            worst_num = max(int(p_level[-1]), int(s_level[-1]), int(r_level[-1]), int(t_level[-1]))
            overall_c = f"C-{worst_num}"

            self._usr_seq += 1
            self.tables["netusr_unit_status_reports"].append(
                {
                    "usr_report_id": f"USR-{self._usr_seq}",
                    "uic": uic,
                    "unit_name": unit_def.unit_name,
                    "report_date": current_date.isoformat(),
                    "auth_personnel": auth_p,
                    "assigned_personnel": assigned_p,
                    "available_deployable_personnel": avail_p,
                    "p_fill_pct": p_fill_pct,
                    "p_level": p_level,
                    "pacing_equip_total": total_eq,
                    "pacing_equip_fmc": fmc_eq,
                    "s_onhand_pct": s_onhand_pct,
                    "s_level": s_level,
                    "r_fmc_pct": r_fmc_pct,
                    "r_level": r_level,
                    "metl_t_pct": t_pct,
                    "t_level": t_level,
                    "overall_c_level": overall_c,
                }
            )

    @staticmethod
    def _score_to_rating(pct: float, thresholds: tuple[float, float, float]) -> str:
        if pct >= thresholds[0]:
            return "C-1"
        if pct >= thresholds[1]:
            return "C-2"
        if pct >= thresholds[2]:
            return "C-3"
        return "C-4"

    def _finalize_master_tables(self, end_date: date) -> None:
        """Captures current state of IPPS-A Soldier Master and GCSS-Army Equipment Master."""
        for dodid, s_ctx in self.soldier_entities.items():
            a = s_ctx.attributes
            self.tables["ippsa_soldier_master"].append(
                {
                    "dodid": a["dodid"],
                    "ssn_hash": a["ssn_hash"],
                    "last_name": a["last_name"],
                    "first_name": a["first_name"],
                    "pay_grade": a["pay_grade"],
                    "rank_code": a["rank_code"],
                    "primary_mos": a["mos"],
                    "assigned_uic": a["assigned_uic"],
                    "billet_id": a["billet_id"],
                    "duty_status": a["duty_status"],
                    "deployable_flag": bool(a["deployable_flag"]),
                    "security_clearance": a["security_clearance"],
                    "tis_months": a["tis_months"],
                    "tig_months": a["tig_months"],
                    "pebd_date": a["pebd_date"],
                    "ets_date": a["ets_date"],
                    "current_fsm_state": s_ctx.current_state,
                    "updated_at": end_date.isoformat(),
                }
            )

        for eq_num, e_ctx in self.equipment_entities.items():
            a = e_ctx.attributes
            self.tables["gcssa_equipment_master"].append(
                {
                    "equipment_number": a["equipment_number"],
                    "serial_number": a["serial_number"],
                    "bumper_number": a["bumper_number"],
                    "owning_uic": a["owning_uic"],
                    "dodaac": a["dodaac"],
                    "lin": a["lin"],
                    "niin": a["niin"],
                    "nsn": a["nsn"],
                    "nomenclature": a["nomenclature"],
                    "erc_code": a["erc_code"],
                    "materiel_status": a["materiel_status"],
                    "operating_hours": a["operating_hours"],
                    "acquisition_cost": a["acquisition_cost"],
                    "current_fsm_state": e_ctx.current_state,
                    "updated_at": end_date.isoformat(),
                }
            )

        # Clean up internal helper pointers from work orders
        for wo in self.tables["gcssa_work_orders"]:
            wo.pop("_selected_part", None)
            wo.pop("_active_req", None)

    def _collect_state_history(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        all_entities = (
            list(self.unit_entities.values())
            + list(self.soldier_entities.values())
            + list(self.equipment_entities.values())
        )
        for ctx in all_entities:
            for h in ctx.history:
                records.append(
                    {
                        "entity_id": h.entity_id,
                        "entity_type": h.entity_type,
                        "module_name": h.module_name,
                        "from_state": h.from_state,
                        "to_state": h.to_state,
                        "entered_date": h.entered_date.isoformat(),
                        "exited_date": h.exited_date.isoformat() if h.exited_date else None,
                    }
                )
        return records

    def _generate_raw_cdc_stream(self) -> None:
        """
        Generates a Bronze-layer CDC envelope stream (`raw_cdc_stream`) across all source tables,
        injecting realistic source-system integration challenges controlled by `messiness_rate`:
          - Duplicate CDC delivery events
          - Legacy UIC formatting drift (e.g. 'WAA1A0 ' or 'UIC-WAA1A0')
          - Missing optional foreign keys requiring Silver-layer imputation/resolution
        """
        cdc_seq = 0
        for table_name, rows in self.tables.items():
            source_sys = table_name.split("_")[0].upper()
            for row in rows:
                cdc_seq += 1
                payload = dict(row)

                # Inject controlled source-system anomalies on a subset of CDC records
                is_messy = self.rng.random() < self.config.messiness_rate
                anomaly_tag = "CLEAN"
                if is_messy:
                    if "owning_uic" in payload and self.rng.random() < 0.5:
                        payload["owning_uic"] = f" {payload['owning_uic'].lower()} "
                        anomaly_tag = "UIC_WHITESPACE_CASE_DRIFT"
                    elif "assigned_uic" in payload:
                        payload["assigned_uic"] = f"UIC:{payload['assigned_uic']}"
                        anomaly_tag = "LEGACY_UIC_PREFIX"

                envelope = {
                    "_cdc_seq": cdc_seq,
                    "_source_system": source_sys,
                    "_source_table": table_name,
                    "_cdc_op": "I",
                    "_anomaly_injected": anomaly_tag,
                    "payload": payload,
                }
                self.raw_cdc_stream.append(envelope)

                # Occasionally emit a duplicate CDC message with identical key
                if is_messy and self.rng.random() < 0.35:
                    cdc_seq += 1
                    dup_envelope = dict(envelope)
                    dup_envelope["_cdc_seq"] = cdc_seq
                    dup_envelope["_cdc_op"] = "U"
                    dup_envelope["_anomaly_injected"] = "DUPLICATE_CDC_DELIVERY"
                    self.raw_cdc_stream.append(dup_envelope)
