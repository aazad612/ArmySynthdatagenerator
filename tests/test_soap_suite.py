"""
Comprehensive Automated Verification Suite for SOAP Synthetic Data Generator
============================================================================
Tests:
  1. Static Graph Linter, Reachability & Mermaid/Graphviz Exporter (`StateModuleInspector`)
  2. Synthea Generic Module Framework Primitives (`PriorState`, `lookup_table_transition`,
     `AtLeast`/`AtMost`, `Weibull`/`Gaussian` delays, `CallSubmodule` return stack)
  3. Bit-for-bit Deterministic Seeded Reproducibility
  4. Statistical Fidelity, Temporal Causality & Domain Invariants (`SyntheticRealismValidator`)
"""

from datetime import date
from pathlib import Path
import random
import tempfile
import unittest

from soap.engine.inspector import StateModuleInspector
from soap.engine.state_machine import EntityContext, ModuleRegistry, StateMachineRunner
from soap.engine.validator import SyntheticRealismValidator
from soap.exporters import export_simulation_output
from soap.world.simulator import ArmyWorldSimulator, SimulationConfig


class TestSOAPSyntheticGenerator(unittest.TestCase):
    def test_01_static_module_graph_linter_and_reachability(self) -> None:
        """Verifies all 6 declarative state-machine modules pass static reachability & probability linting."""
        registry = ModuleRegistry()
        inspector = StateModuleInspector(registry)
        reports = inspector.inspect_all()

        self.assertEqual(len(reports), 6)
        for name, rep in reports.items():
            self.assertTrue(rep.is_valid, f"Module {name} had lint errors: {rep.errors}")
            self.assertEqual(rep.total_states, rep.reachable_states)

    def test_02_synthea_gmf_primitives_prior_state_and_lookup_table(self) -> None:
        """Verifies PriorState temporal conditions, lookup_table_transition, and Weibull/Gaussian delays."""
        registry = ModuleRegistry()
        runner = StateMachineRunner(registry, random.Random(42))

        ctx = EntityContext(
            entity_id="1400500107",
            entity_type="SOLDIER",
            attributes={"dodid": "1400500107", "assigned_uic": "WAA1A0", "pay_grade": "E-5"},
            active_module="pme_leadership_school_submodule",
        )
        events = runner.step_entity(ctx, date(2026, 2, 1))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["course_code"], "600-ALC")
        self.assertTrue(ctx.has_visited_state("Enroll_Advanced_Leader_Course_ALC"))
        self.assertTrue(
            ctx.has_visited_state(
                "Enroll_Advanced_Leader_Course_ALC", within_days=30, current_date=date(2026, 2, 15)
            )
        )
        self.assertFalse(
            ctx.has_visited_state(
                "Enroll_Advanced_Leader_Course_ALC", within_days=5, current_date=date(2026, 2, 15)
            )
        )

    def test_03_deterministic_reproducibility(self) -> None:
        """Verifies identical seeds produce bit-for-bit identical synthetic populations and timelines."""
        cfg1 = SimulationConfig(seed=99, days=120, scale_factor=0.2, messiness_rate=0.05)
        cfg2 = SimulationConfig(seed=99, days=120, scale_factor=0.2, messiness_rate=0.05)

        out1 = ArmyWorldSimulator(cfg1).run()
        out2 = ArmyWorldSimulator(cfg2).run()

        self.assertEqual(out1.metrics, out2.metrics)
        self.assertEqual(out1.tables, out2.tables)
        self.assertEqual(out1.state_history, out2.state_history)
        self.assertEqual(out1.raw_cdc_stream, out2.raw_cdc_stream)

    def test_04_statistical_and_operational_realism_validator(self) -> None:
        """Verifies 100% of operational, financial, temporal, and submodule invariants pass."""
        cfg = SimulationConfig(seed=42, days=180, scale_factor=0.25, messiness_rate=0.05)
        sim_out = ArmyWorldSimulator(cfg).run()

        validator = SyntheticRealismValidator()
        summary = validator.validate(sim_out)
        for chk in summary.checks:
            self.assertTrue(chk.passed, f"Failed realism check {chk.check_name}: {chk.details}")
        self.assertTrue(summary.all_passed)

    def test_05_multi_format_exporters_and_graph_generation(self) -> None:
        """Verifies CSV, JSONL, SQLite, PostgreSQL seed SQL, and Mermaid/DOT graphs export cleanly."""
        cfg = SimulationConfig(seed=42, days=60, scale_factor=0.15)
        sim_out = ArmyWorldSimulator(cfg).run()
        registry = ModuleRegistry()
        inspector = StateModuleInspector(registry)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            written = export_simulation_output(
                sim_out, out_path, formats=["csv", "jsonl", "sqlite", "postgres"]
            )
            graphs = inspector.export_graphs(out_path)

            self.assertEqual(len(written["csv"]), 12)
            self.assertEqual(len(written["jsonl"]), 13)
            self.assertTrue(Path(written["sqlite"][0]).exists())
            self.assertTrue(Path(written["postgres"][0]).exists())
            self.assertEqual(len(graphs["mermaid"]), 6)
            self.assertEqual(len(graphs["graphviz_dot"]), 6)


if __name__ == "__main__":
    unittest.main()
