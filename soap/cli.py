"""
SOAP Command-Line Interface — Synthea-Grade U.S. Army Synthetic Data Generator
==============================================================================
Commands / Capabilities:
  1. Static State-Machine Graph Linter & Mermaid/Graphviz Visualizer (`StateModuleInspector`)
  2. Multi-Domain Longitudinal Simulation (`ArmyWorldSimulator`) across 6 State Modules
  3. Multi-Format Dataset Export (`CSV`, `JSONL`, `SQLite`, `PostgreSQL Seed SQL`, `Mermaid/DOT Graphs`)
  4. Automated Statistical & Domain Realism Validation (`SyntheticRealismValidator`)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict

from soap.engine.inspector import ModuleInspectionReport, StateModuleInspector
from soap.engine.state_machine import ModuleRegistry
from soap.engine.validator import RealismValidationSummary, SyntheticRealismValidator
from soap.exporters import export_simulation_output
from soap.world.simulator import ArmyWorldSimulator, SimulationConfig, SimulationOutput


def _print_banner() -> None:
    print("=" * 96)
    print(" SOAP: SYNTHETIC OPERATIONAL ARMY PLATFORM (Synthea-Grade Generic Module Framework)")
    print(" Declarative State-Machine Synthetic Data Generator for U.S. Army Enterprise Systems")
    print(" Domains: FMSWeb (MTOE) | IPPS-A (Personnel) | GCSS-Army (Logistics) | DTMS/NetUSR | GFEBS")
    print("=" * 96)


def _print_report(
    module_reports: Dict[str, ModuleInspectionReport],
    sim_output: SimulationOutput,
    realism_summary: RealismValidationSummary,
    output_dir: Path,
) -> None:
    print("\n[1] STATE-MACHINE MODULE GRAPH LINTER & STATIC REACHABILITY ANALYSIS")
    print("-" * 96)
    print(
        f"  {'MODULE NAME':<36} {'STATES':>7} {'REACHABLE':>10} {'EDGES':>7} {'SUBMODULES':<24} {'STATUS':<8}"
    )
    for name, rep in module_reports.items():
        subs = ", ".join(rep.submodule_calls) if rep.submodule_calls else "-"
        status = "VALID" if rep.is_valid else "INVALID"
        print(
            f"  {name:<36} {rep.total_states:>7} {rep.reachable_states:>10} "
            f"{rep.transition_edges_count:>7} {subs[:23]:<24} {status:<8}"
        )

    m = sim_output.metrics
    print("\n[2] LONGITUDINAL SIMULATION & SYNTHETIC DATASET VOLUMES")
    print("-" * 96)
    print(
        f"  Simulation Horizon            : {m['simulation_start_date']} to {m['simulation_end_date']} ({m['total_days']} days, Seed={m['seed']})"
    )
    for tbl_name, rows in sim_output.tables.items():
        print(f"  {tbl_name:<36} : {len(rows):>8,} records")
    print(f"  {'fsm_state_history (Audit Trail)':<36} : {m['state_transitions_count']:>8,} state transitions")
    print(f"  {'raw_cdc_stream (CDC Envelopes)':<36} : {m['raw_cdc_events_count']:>8,} CDC events")

    print("\n[3] STATISTICAL FIDELITY & OPERATIONAL REALISM VALIDATION")
    print("-" * 96)
    for chk in realism_summary.checks:
        badge = "PASS" if chk.passed else "FAIL"
        print(f"  [{badge}] {chk.check_name:<38} : {chk.details}")

    print("\n[4] EXPORTED ARTIFACTS")
    print("-" * 96)
    print(f"  CSV Tables                    : {output_dir / 'csv'}")
    print(f"  JSONL Tables & CDC Stream     : {output_dir / 'jsonl'}")
    print(f"  SQLite Synthetic Database     : {output_dir / 'sqlite' / 'soap_army_synthetic.db'}")
    print(f"  PostgreSQL Bulk Seed Script   : {output_dir / 'postgres' / 'seed_army_synthetic.sql'}")
    print(f"  Mermaid & Graphviz DOT Graphs : {output_dir / 'graphs'}")
    print("=" * 96)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="soap",
        description="SOAP: Synthea-Grade U.S. Army Synthetic Data Generator",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic PRNG seed (default: 42)")
    parser.add_argument("--days", type=int, default=180, help="Simulation duration in days (default: 180)")
    parser.add_argument(
        "--scale",
        type=float,
        default=0.25,
        help="Force MTOE scale factor (0.25 = ~165 soldiers, 1.0 = full Brigade slice)",
    )
    parser.add_argument(
        "--messiness-rate",
        type=float,
        default=0.05,
        help="Controlled CDC anomaly injection rate (default: 0.05)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Output directory for exported datasets and state graphs",
    )
    args = parser.parse_args(argv)

    _print_banner()
    out_dir = Path(args.output_dir)

    # 1. Inspect & export state machine module graphs
    registry = ModuleRegistry()
    inspector = StateModuleInspector(registry)
    module_reports = inspector.inspect_all()
    for rep in module_reports.values():
        if not rep.is_valid:
            raise ValueError(f"Module '{rep.module_name}' failed graph inspection: {rep.errors}")
    inspector.export_graphs(out_dir)

    # 2. Run longitudinal simulation
    cfg = SimulationConfig(
        seed=args.seed,
        days=args.days,
        scale_factor=args.scale,
        messiness_rate=args.messiness_rate,
    )
    simulator = ArmyWorldSimulator(cfg)
    sim_output = simulator.run()

    # 3. Validate statistical & operational realism
    validator = SyntheticRealismValidator()
    realism_summary = validator.validate(sim_output)

    # 4. Export all formats
    export_simulation_output(
        sim_output,
        out_dir,
        formats=["csv", "jsonl", "sqlite", "postgres"],
    )
    val_path = out_dir / "realism_validation_report.json"
    with open(val_path, "w", encoding="utf-8") as f:
        json.dump(realism_summary.to_dict(), f, indent=2)

    _print_report(module_reports, sim_output, realism_summary, out_dir)
    return 0 if realism_summary.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
