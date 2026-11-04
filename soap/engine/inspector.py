"""
Synthea-Style State Module Static Graph Analyzer, Linter & Graphviz/Mermaid Visualizer.

Validates declarative JSON state modules for:
  1. Graph reachability from 'Initial' (zero unreachable/orphan states)
  2. Target state existence on all transition edges
  3. Probability distribution normalization (weights summing to 1.0)
  4. Valid submodule references on CallSubmodule states
  5. Non-terminal dead-end detection
And exports Graphviz (.dot) and Mermaid (.mmd) state-machine diagrams.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from soap.engine.state_machine import ModuleRegistry


@dataclass
class ModuleInspectionReport:
    module_name: str
    total_states: int
    reachable_states: int
    terminal_states: int
    submodule_calls: List[str]
    transition_edges_count: int
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


class StateModuleInspector:
    """Static graph linter and Graphviz/Mermaid exporter for declarative state modules."""

    def __init__(self, registry: ModuleRegistry) -> None:
        self.registry = registry

    def inspect_all(self) -> Dict[str, ModuleInspectionReport]:
        reports: Dict[str, ModuleInspectionReport] = {}
        for name in sorted(self.registry.modules.keys()):
            reports[name] = self.inspect_module(name)
        return reports

    def inspect_module(self, module_name: str) -> ModuleInspectionReport:
        mod = self.registry.get_module(module_name)
        states: Dict[str, Dict[str, Any]] = mod["states"]
        errors: List[str] = []
        warnings: List[str] = []
        submodules: List[str] = []

        edges_by_state: Dict[str, List[Tuple[str, str]]] = {}
        total_edges = 0
        terminal_count = 0

        for s_name, s_def in states.items():
            stype = s_def.get("type", "Simple")
            if stype == "Terminal":
                terminal_count += 1
            if stype == "CallSubmodule":
                sub = s_def.get("submodule", "")
                submodules.append(sub)
                if sub not in self.registry.modules:
                    errors.append(f"State '{s_name}' calls unknown submodule '{sub}'.")

            targets = self._extract_labeled_edges(s_name, s_def, errors)
            edges_by_state[s_name] = targets
            total_edges += len(targets)

            for target_state, _ in targets:
                if target_state not in states:
                    errors.append(
                        f"State '{s_name}' transitions to non-existent state '{target_state}'."
                    )

            if stype != "Terminal" and len(targets) == 0:
                errors.append(f"Non-terminal state '{s_name}' (type={stype}) has no outgoing transitions.")

        # BFS from Initial to verify reachability
        visited: Set[str] = set()
        if "Initial" in states:
            queue = deque(["Initial"])
            visited.add("Initial")
            while queue:
                curr = queue.popleft()
                for nxt, _ in edges_by_state.get(curr, []):
                    if nxt in states and nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)

        unreachable = set(states.keys()) - visited
        for u in sorted(unreachable):
            errors.append(f"State '{u}' is unreachable from 'Initial'.")

        return ModuleInspectionReport(
            module_name=module_name,
            total_states=len(states),
            reachable_states=len(visited),
            terminal_states=terminal_count,
            submodule_calls=submodules,
            transition_edges_count=total_edges,
            errors=errors,
            warnings=warnings,
        )

    def _extract_labeled_edges(
        self, state_name: str, state_def: Dict[str, Any], errors: List[str]
    ) -> List[Tuple[str, str]]:
        edges: List[Tuple[str, str]] = []
        if "direct_transition" in state_def:
            edges.append((state_def["direct_transition"], "direct"))

        if "distributed_transition" in state_def:
            dists = state_def["distributed_transition"]
            self._check_weights_sum(state_name, dists, errors)
            for d in dists:
                w = d.get("distribution", d.get("default_weight", 0.0))
                edges.append((d["transition"], f"{float(w)*100:.0f}%"))

        if "conditional_transition" in state_def:
            for idx, branch in enumerate(state_def["conditional_transition"], start=1):
                edges.append((branch["transition"], f"cond #{idx}"))

        if "complex_transition" in state_def:
            for idx, branch in enumerate(state_def["complex_transition"], start=1):
                if "transition" in branch:
                    edges.append((branch["transition"], f"branch #{idx}"))
                if "distributions" in branch:
                    self._check_weights_sum(f"{state_name}[branch #{idx}]", branch["distributions"], errors)
                    for d in branch["distributions"]:
                        w = float(d.get("distribution", 0.0))
                        edges.append((d["transition"], f"b{idx}:{w*100:.0f}%"))

        if "lookup_table_transition" in state_def:
            lt = state_def["lookup_table_transition"]
            for idx, rule in enumerate(lt.get("rules", []), start=1):
                dists = rule.get("distributions", [])
                self._check_weights_sum(f"{state_name}[lookup #{idx}]", dists, errors)
                for d in dists:
                    edges.append((d["transition"], f"lookup #{idx}"))
            if "default_transition" in lt:
                edges.append((lt["default_transition"], "default"))
            for d in lt.get("default_distributions", []):
                edges.append((d["transition"], "default_dist"))

        return edges

    @staticmethod
    def _check_weights_sum(context_label: str, dists: List[Dict[str, Any]], errors: List[str]) -> None:
        if not dists or any("attribute_weight" in d for d in dists):
            return
        total = sum(float(d.get("distribution", 0.0)) for d in dists)
        if abs(total - 1.0) > 1e-5:
            errors.append(f"Distribution in '{context_label}' sums to {total:.4f} (expected 1.0).")

    def export_graphs(self, output_dir: Path) -> Dict[str, List[str]]:
        """Exports all state modules as both Mermaid (.mmd) and Graphviz (.dot) diagrams."""
        graphs_dir = output_dir / "graphs"
        graphs_dir.mkdir(parents=True, exist_ok=True)
        written: Dict[str, List[str]] = {"mermaid": [], "graphviz_dot": []}

        for name, mod in sorted(self.registry.modules.items()):
            mmd_path = graphs_dir / f"{name}.mmd"
            dot_path = graphs_dir / f"{name}.dot"
            mmd_path.write_text(self.to_mermaid(name, mod), encoding="utf-8")
            dot_path.write_text(self.to_graphviz_dot(name, mod), encoding="utf-8")
            written["mermaid"].append(str(mmd_path))
            written["graphviz_dot"].append(str(dot_path))
        return written

    def to_mermaid(self, module_name: str, mod: Dict[str, Any]) -> str:
        lines = [f"flowchart TD", f"    %% Module: {module_name}"]
        states = mod["states"]
        for s_name, s_def in states.items():
            stype = s_def.get("type", "Simple")
            label = f"{s_name} ({stype})"
            if stype == "CallSubmodule":
                label = f"{s_name} [Call: {s_def.get('submodule')}]"
            elif stype == "EmitEvent":
                label = f"{s_name} [Emit: {s_def.get('event_type')}]"
            lines.append(f'    {s_name}["{label}"]')
            for target, edge_lbl in self._extract_labeled_edges(s_name, s_def, []):
                lines.append(f'    {s_name} -->|"{edge_lbl}"| {target}')
        return "\n".join(lines) + "\n"

    def to_graphviz_dot(self, module_name: str, mod: Dict[str, Any]) -> str:
        lines = [
            f'digraph "{module_name}" {{',
            '    rankdir=TB;',
            '    node [shape=box, style="rounded,filled", fillcolor="#F5F7FA", fontname="Helvetica"];',
        ]
        states = mod["states"]
        for s_name, s_def in states.items():
            stype = s_def.get("type", "Simple")
            color = "#E3F2FD" if stype in ("Initial", "Terminal") else "#F5F7FA"
            if stype == "EmitEvent":
                color = "#E8F5E9"
            elif stype == "CallSubmodule":
                color = "#FFF3E0"
            lines.append(f'    "{s_name}" [label="{s_name}\\n({stype})", fillcolor="{color}"];')
            for target, edge_lbl in self._extract_labeled_edges(s_name, s_def, []):
                lines.append(f'    "{s_name}" -> "{target}" [label="{edge_lbl}"];')
        lines.append("}")
        return "\n".join(lines) + "\n"
