"""
Synthea-Architected Generic Module Framework (GMF) State Machine Engine for U.S. Army Entities.

Implements the complete MITRE Synthea state-machine specification adapted for military operations:
  - State Types:
      * Initial: Module entry point
      * Simple: Organizational / branching node
      * Delay: Exact duration, Uniform range, Gaussian/Normal, Exponential, or Weibull hazard delay
      * Guard: Blocks entity progression until a composite predicate tree evaluates True
      * SetAttribute: Sets attribute via literal, attribute copy, parametric distribution, or formula
      * Counter: Increments or decrements numeric attributes
      * EmitEvent: Emits a typed, timestamped domain record to a target Army system stream
      * CallSubmodule: Pushes return frame onto entity call stack and enters a reusable submodule
      * Terminal: Pops submodule call stack (returning to caller) or terminates the entity lifecycle
  - Transition Types:
      * direct_transition
      * distributed_transition (static weights or dynamic attribute-scaled weights)
      * conditional_transition
      * complex_transition
      * lookup_table_transition (multi-attribute table matching with row-level probability distributions)
  - Condition Predicates:
      * And, Or, Not, AtLeast (k-of-n), AtMost (k-of-n), True, False
      * Attribute (==, !=, >, >=, <, <=, in, is_nil, is_not_nil)
      * PriorState (checks whether entity visited a state previously, optionally within N days)
      * SimDate (checks current simulation month, quarter, or year)
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


SUPPORTED_STATE_TYPES: Set[str] = {
    "Initial",
    "Simple",
    "Delay",
    "Guard",
    "SetAttribute",
    "Counter",
    "EmitEvent",
    "CallSubmodule",
    "Terminal",
}


@dataclass
class StateTransitionRecord:
    entity_id: str
    entity_type: str
    module_name: str
    from_state: str
    to_state: str
    entered_date: date
    exited_date: Optional[date] = None


@dataclass
class SimulationEvent:
    event_id: str
    event_date: date
    source_system: str  # FMSWEB, IPPSA, GCSS_ARMY, DTMS_USR, GFEBS
    event_type: str
    entity_id: str
    entity_type: str
    module_name: str
    state_name: str
    payload: Dict[str, Any]


@dataclass
class CallStackFrame:
    module_name: str
    return_state: str


@dataclass
class EntityContext:
    entity_id: str
    entity_type: str  # SOLDIER, EQUIPMENT, UNIT
    attributes: Dict[str, Any]
    active_module: str
    current_state: str = "Initial"
    state_entered_date: Optional[date] = None
    delay_until_date: Optional[date] = None
    is_terminated: bool = False
    call_stack: List[CallStackFrame] = field(default_factory=list)
    history: List[StateTransitionRecord] = field(default_factory=list)

    def has_visited_state(
        self,
        state_name: str,
        module_name: Optional[str] = None,
        within_days: Optional[int] = None,
        current_date: Optional[date] = None,
    ) -> bool:
        """Synthea `PriorState` check: returns True if entity previously transitioned through `state_name`."""
        for rec in reversed(self.history):
            if rec.from_state == state_name or rec.to_state == state_name:
                if module_name is not None and rec.module_name != module_name:
                    continue
                if within_days is not None and current_date is not None:
                    ref_date = rec.exited_date or rec.entered_date
                    if (current_date - ref_date).days > within_days:
                        continue
                return True
        return False


class ModuleRegistry:
    """Loads, validates, and indexes declarative JSON state-machine modules."""

    def __init__(self, modules_dir: Optional[Path] = None) -> None:
        self.modules: Dict[str, Dict[str, Any]] = {}
        if modules_dir is None:
            modules_dir = Path(__file__).resolve().parent.parent / "modules"
        self.modules_dir = modules_dir
        if self.modules_dir.exists():
            self.load_directory(self.modules_dir)

    def load_directory(self, directory: Path) -> None:
        for path in sorted(directory.glob("*.json")):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            module_name = data.get("name", path.stem)
            self._validate_module(module_name, data)
            self.modules[module_name] = data

    def _validate_module(self, module_name: str, data: Dict[str, Any]) -> None:
        if "states" not in data or not isinstance(data["states"], dict):
            raise ValueError(f"Module '{module_name}' missing 'states' dictionary.")
        states = data["states"]
        if "Initial" not in states:
            raise ValueError(f"Module '{module_name}' must contain an 'Initial' state.")
        for state_name, state_def in states.items():
            stype = state_def.get("type")
            if stype not in SUPPORTED_STATE_TYPES:
                raise ValueError(
                    f"Module '{module_name}', state '{state_name}' has unsupported type '{stype}'."
                )

    def get_module(self, name: str) -> Dict[str, Any]:
        if name not in self.modules:
            raise KeyError(f"State module '{name}' not found in registry.")
        return self.modules[name]


class StateMachineRunner:
    """
    Executes declarative state modules against EntityContext instances at each simulation tick.
    """

    def __init__(self, registry: ModuleRegistry, rng: random.Random) -> None:
        self.registry = registry
        self.rng = rng
        self._event_seq = 0

    def _next_event_id(self, prefix: str = "EVT") -> str:
        self._event_seq += 1
        return f"{prefix}-{self._event_seq:08d}"

    def evaluate_condition(self, cond: Dict[str, Any], entity: EntityContext, current_date: date) -> bool:
        """Evaluates Synthea-style composite predicate trees against entity attributes, history, and clock."""
        ctype = cond.get("condition_type", "Attribute")

        if ctype == "And":
            return all(
                self.evaluate_condition(sub, entity, current_date)
                for sub in cond.get("conditions", [])
            )
        if ctype == "Or":
            return any(
                self.evaluate_condition(sub, entity, current_date)
                for sub in cond.get("conditions", [])
            )
        if ctype == "Not":
            sub = cond.get("condition", {})
            return not self.evaluate_condition(sub, entity, current_date)
        if ctype == "AtLeast":
            minimum = int(cond.get("minimum", 1))
            passed = sum(
                1 for sub in cond.get("conditions", []) if self.evaluate_condition(sub, entity, current_date)
            )
            return passed >= minimum
        if ctype == "AtMost":
            maximum = int(cond.get("maximum", 1))
            passed = sum(
                1 for sub in cond.get("conditions", []) if self.evaluate_condition(sub, entity, current_date)
            )
            return passed <= maximum
        if ctype == "True":
            return True
        if ctype == "False":
            return False

        if ctype == "PriorState":
            target_state = cond["name"]
            target_module = cond.get("module")
            within_days = cond.get("within_days")
            return entity.has_visited_state(
                state_name=target_state,
                module_name=target_module,
                within_days=int(within_days) if within_days is not None else None,
                current_date=current_date,
            )

        if ctype == "SimDate":
            field_name = cond.get("field", "month")  # month, quarter, year
            operator = cond.get("operator", "==")
            expected = cond.get("value")
            if field_name == "month":
                actual_val = current_date.month
            elif field_name == "quarter":
                actual_val = ((current_date.month - 1) // 3) + 1
            else:
                actual_val = current_date.year
            return self._compare_values(actual_val, operator, expected)

        # Default: Attribute condition
        attr_name = cond.get("attribute", "")
        operator = cond.get("operator", "==")
        expected = cond.get("value")
        actual = entity.attributes.get(attr_name)

        if operator == "is_nil":
            return actual is None
        if operator == "is_not_nil":
            return actual is not None
        if actual is None:
            return False

        return self._compare_values(actual, operator, expected)

    @staticmethod
    def _compare_values(actual: Any, operator: str, expected: Any) -> bool:
        if operator == "==":
            return actual == expected
        if operator == "!=":
            return actual != expected
        if operator == ">":
            return actual > expected
        if operator == ">=":
            return actual >= expected
        if operator == "<":
            return actual < expected
        if operator == "<=":
            return actual <= expected
        if operator == "in":
            return actual in (expected or [])
        raise ValueError(f"Unsupported condition operator: {operator}")

    def resolve_next_state(
        self, state_def: Dict[str, Any], entity: EntityContext, current_date: date
    ) -> Optional[str]:
        """Resolves direct, distributed, conditional, complex, or lookup_table transitions."""
        if "direct_transition" in state_def:
            return state_def["direct_transition"]

        if "distributed_transition" in state_def:
            return self._sample_distribution(state_def["distributed_transition"], entity)

        if "conditional_transition" in state_def:
            for branch in state_def["conditional_transition"]:
                cond = branch.get("condition")
                if cond is None or self.evaluate_condition(cond, entity, current_date):
                    return branch["transition"]
            return None

        if "complex_transition" in state_def:
            for branch in state_def["complex_transition"]:
                cond = branch.get("condition")
                if cond is None or self.evaluate_condition(cond, entity, current_date):
                    if "distributions" in branch:
                        return self._sample_distribution(branch["distributions"], entity)
                    if "transition" in branch:
                        return branch["transition"]
            return None

        if "lookup_table_transition" in state_def:
            return self._resolve_lookup_table_transition(state_def["lookup_table_transition"], entity)

        return None

    def _sample_distribution(
        self, distributions: List[Dict[str, Any]], entity: Optional[EntityContext] = None
    ) -> str:
        weights: List[float] = []
        for item in distributions:
            if entity is not None and "attribute_weight" in item:
                w = float(entity.attributes.get(item["attribute_weight"], item.get("default_weight", 0.1)))
            else:
                w = float(item["distribution"])
            weights.append(max(0.0, w))

        total = sum(weights)
        if total <= 0.0:
            return distributions[-1]["transition"]

        roll = self.rng.uniform(0.0, total)
        cumulative = 0.0
        for item, w in zip(distributions, weights):
            cumulative += w
            if roll <= cumulative + 1e-9:
                return item["transition"]
        return distributions[-1]["transition"]

    def _resolve_lookup_table_transition(
        self, lookup_spec: Dict[str, Any], entity: EntityContext
    ) -> Optional[str]:
        """
        Synthea `lookup_table_transition`: matches entity attributes against ordered rows
        in `rules` and samples from the matching row's `distributions`.
        """
        for rule in lookup_spec.get("rules", []):
            match_attrs: Dict[str, Any] = rule.get("match", {})
            is_match = True
            for k, expected in match_attrs.items():
                actual = entity.attributes.get(k)
                if isinstance(expected, list):
                    if actual not in expected:
                        is_match = False
                        break
                elif actual != expected:
                    is_match = False
                    break
            if is_match:
                return self._sample_distribution(rule["distributions"], entity)

        default_dist = lookup_spec.get("default_distributions")
        if default_dist:
            return self._sample_distribution(default_dist, entity)
        return lookup_spec.get("default_transition")

    def step_entity(
        self, entity: EntityContext, current_date: date, max_transitions_per_tick: int = 16
    ) -> List[SimulationEvent]:
        """
        Advances an entity through its state machine at `current_date` until it hits
        a waiting Delay, an unsatisfied Guard, or a Terminal state.
        """
        emitted: List[SimulationEvent] = []
        if entity.is_terminated:
            return emitted

        if entity.state_entered_date is None:
            entity.state_entered_date = current_date

        transitions = 0
        while transitions < max_transitions_per_tick and not entity.is_terminated:
            module = self.registry.get_module(entity.active_module)
            state_def = module["states"][entity.current_state]
            stype = state_def["type"]

            # 1. Handle waiting logic for Delay or Guard states
            if stype == "Delay":
                if entity.delay_until_date is None:
                    days = self._compute_delay_days(state_def)
                    entity.delay_until_date = current_date + timedelta(days=days)
                if current_date < entity.delay_until_date:
                    break  # Still waiting in Delay state
                # Delay completed: clear timer and transition out
                entity.delay_until_date = None

            elif stype == "Guard":
                allow_cond = state_def.get("allow", {"condition_type": "True"})
                if not self.evaluate_condition(allow_cond, entity, current_date):
                    break  # Blocked on Guard condition

            elif stype == "SetAttribute":
                self._apply_set_attribute(state_def, entity)

            elif stype == "Counter":
                attr = state_def["attribute"]
                action = state_def.get("action", "increment")
                amount = state_def.get("amount", 1)
                current_val = entity.attributes.get(attr, 0)
                if action == "increment":
                    entity.attributes[attr] = current_val + amount
                elif action == "decrement":
                    entity.attributes[attr] = current_val - amount

            elif stype == "EmitEvent":
                payload = dict(state_def.get("payload", {}))
                for k, attr_key in state_def.get("attribute_bindings", {}).items():
                    payload[k] = entity.attributes.get(attr_key)
                event = SimulationEvent(
                    event_id=self._next_event_id(state_def.get("event_prefix", "EVT")),
                    event_date=current_date,
                    source_system=state_def["source_system"],
                    event_type=state_def["event_type"],
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    module_name=entity.active_module,
                    state_name=entity.current_state,
                    payload=payload,
                )
                emitted.append(event)

            elif stype == "CallSubmodule":
                return_state = self.resolve_next_state(state_def, entity, current_date)
                if return_state is None:
                    raise ValueError(
                        f"CallSubmodule state '{entity.current_state}' in '{entity.active_module}' has no return transition."
                    )
                submodule_name = state_def["submodule"]
                entity.call_stack.append(
                    CallStackFrame(module_name=entity.active_module, return_state=return_state)
                )
                entity.history.append(
                    StateTransitionRecord(
                        entity_id=entity.entity_id,
                        entity_type=entity.entity_type,
                        module_name=entity.active_module,
                        from_state=entity.current_state,
                        to_state=f"{submodule_name}:Initial",
                        entered_date=entity.state_entered_date or current_date,
                        exited_date=current_date,
                    )
                )
                entity.active_module = submodule_name
                entity.current_state = "Initial"
                entity.state_entered_date = current_date
                transitions += 1
                continue

            elif stype == "Terminal":
                if entity.call_stack:
                    frame = entity.call_stack.pop()
                    entity.history.append(
                        StateTransitionRecord(
                            entity_id=entity.entity_id,
                            entity_type=entity.entity_type,
                            module_name=entity.active_module,
                            from_state=entity.current_state,
                            to_state=f"{frame.module_name}:{frame.return_state}",
                            entered_date=entity.state_entered_date or current_date,
                            exited_date=current_date,
                        )
                    )
                    entity.active_module = frame.module_name
                    entity.current_state = frame.return_state
                    entity.state_entered_date = current_date
                    transitions += 1
                    continue
                else:
                    entity.is_terminated = True
                    break

            # 2. Resolve transition to next state
            next_state = self.resolve_next_state(state_def, entity, current_date)
            if next_state is None:
                break

            entity.history.append(
                StateTransitionRecord(
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    module_name=entity.active_module,
                    from_state=entity.current_state,
                    to_state=next_state,
                    entered_date=entity.state_entered_date or current_date,
                    exited_date=current_date,
                )
            )
            entity.current_state = next_state
            entity.state_entered_date = current_date
            transitions += 1

        return emitted

    def _apply_set_attribute(self, state_def: Dict[str, Any], entity: EntityContext) -> None:
        attr = state_def["attribute"]
        if "value" in state_def:
            entity.attributes[attr] = state_def["value"]
        elif "value_from_attribute" in state_def:
            entity.attributes[attr] = entity.attributes.get(state_def["value_from_attribute"])
        elif "distribution" in state_def:
            dist = state_def["distribution"]
            kind = dist.get("kind", "UNIFORM").upper()
            if kind == "UNIFORM":
                val = self.rng.uniform(float(dist["low"]), float(dist["high"]))
            elif kind in ("GAUSSIAN", "NORMAL"):
                val = self.rng.gauss(float(dist["mean"]), float(dist["std_dev"]))
                if "min" in dist:
                    val = max(float(dist["min"]), val)
                if "max" in dist:
                    val = min(float(dist["max"]), val)
            elif kind == "EXPONENTIAL":
                mean = float(dist.get("mean", 10.0))
                val = self.rng.expovariate(1.0 / max(1e-6, mean))
            elif kind == "WEIBULL":
                scale = float(dist.get("scale", 10.0))
                shape = float(dist.get("shape", 1.5))
                val = self.rng.weibullvariate(scale, shape)
            else:
                val = 0.0
            entity.attributes[attr] = int(round(val)) if dist.get("round_int", False) else round(val, 2)

    def _compute_delay_days(self, state_def: Dict[str, Any]) -> int:
        if "exact" in state_def:
            qty = float(state_def["exact"]["quantity"])
            unit = state_def["exact"].get("unit", "days")
            return max(1, int(round(self._convert_to_days(qty, unit))))
        if "range" in state_def:
            low = float(state_def["range"]["low"])
            high = float(state_def["range"]["high"])
            unit = state_def["range"].get("unit", "days")
            raw = self.rng.uniform(low, high)
            return max(1, int(round(self._convert_to_days(raw, unit))))
        if "distribution" in state_def:
            dist = state_def["distribution"]
            kind = dist.get("kind", "GAUSSIAN").upper()
            unit = dist.get("unit", "days")
            if kind in ("GAUSSIAN", "NORMAL"):
                raw = self.rng.gauss(float(dist["mean"]), float(dist["std_dev"]))
            elif kind == "EXPONENTIAL":
                raw = self.rng.expovariate(1.0 / max(1e-6, float(dist.get("mean", 7.0))))
            elif kind == "WEIBULL":
                raw = self.rng.weibullvariate(float(dist.get("scale", 10.0)), float(dist.get("shape", 2.0)))
            else:
                raw = float(dist.get("mean", 7.0))
            if "min" in dist:
                raw = max(float(dist["min"]), raw)
            if "max" in dist:
                raw = min(float(dist["max"]), raw)
            return max(1, int(round(self._convert_to_days(raw, unit))))
        return 1

    @staticmethod
    def _convert_to_days(qty: float, unit: str) -> float:
        u = unit.lower()
        if u in ("hour", "hours"):
            return qty / 24.0
        if u in ("week", "weeks"):
            return qty * 7.0
        if u in ("month", "months"):
            return qty * 30.0
        if u in ("year", "years"):
            return qty * 365.0
        return qty
