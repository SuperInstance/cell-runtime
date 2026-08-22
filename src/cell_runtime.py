"""
cell_runtime — The 8-primitive cell as a working Python type.

The Quilt canon, in code. Every reactive element has 8 primitives:
  Z_in       — inputs (other cells)
  Z_out      — outputs (other cells)
  JEPA       — predictive update
  DoubleEntry — paired state
  Vibe       — position/velocity/acceleration
  GC         — 3-phase garbage collection
  Murmur     — heartbeat
  Graph      — place in the whole

A Cell is a system, not a value. The graph is the truth.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import math
import time
import uuid
import json


# -- The 8 primitives, as a frozen dataclass -------------------------------

@dataclass(frozen=True)
class Vibe:
    """Position, velocity, acceleration through the graph."""
    pos: Tuple[float, ...] = (0.0,)
    vel: Tuple[float, ...] = (0.0,)
    acc: Tuple[float, ...] = (0.0,)

    def step(self, dt: float = 1.0) -> "Vibe":
        # Verlet-ish: pos += vel*dt + 0.5*acc*dt^2; vel += acc*dt
        new_pos = tuple(p + v * dt + 0.5 * a * dt * dt for p, v, a in zip(self.pos, self.vel, self.acc))
        new_vel = tuple(v + a * dt for v, a in zip(self.vel, self.acc))
        return Vibe(pos=new_pos, vel=new_vel, acc=self.acc)

    def nudge(self, target_pos: Tuple[float, ...], k: float = 0.1) -> "Vibe":
        """Apply a spring force toward target_pos. Returns new Vibe."""
        if len(target_pos) != len(self.pos):
            target_pos = target_pos + self.pos[len(target_pos):]
        new_acc = tuple(k * (t - p) for p, t in zip(self.pos, target_pos))
        return Vibe(pos=self.pos, vel=self.vel, acc=new_acc)


# -- The Cell --------------------------------------------------------------

class Cell:
    """
    A reactive element with 8 primitives.

    The cell is a system, not a value. The graph is the truth.
    Two cells with the same address (path from root) are the same cell.
    """

    def __init__(
        self,
        value: Any = None,
        name: Optional[str] = None,
        jepa: Optional[Callable[[Dict[str, Any]], Any]] = None,
        address: Optional[str] = None,
    ):
        self._id = str(uuid.uuid4())[:8]
        self._name = name or f"cell-{self._id}"
        self._address = address or self._name
        self._value = value
        self._jepa = jepa or (lambda inputs: self._value)  # default: hold value
        self._inputs: Dict[str, "Cell"] = {}
        self._outputs: Dict[str, "Cell"] = {}
        self._debit: Any = None  # before
        self._credit: Any = value  # after
        self._vibe: Vibe = Vibe()
        self._gc_phase: int = 0
        self._last_murmur: float = time.time()
        self._murmur_count: int = 0
        self._ticks: int = 0
        self._born: float = time.time()
        self._log: List[Dict[str, Any]] = []

    # -- Z_in / Z_out -------------------------------------------------------

    def connect_from(self, other: "Cell", name: Optional[str] = None, transform: Optional[Callable[[Any], Any]] = None) -> "Cell":
        """Z_in: this cell receives from `other`."""
        key = name or other._name
        if transform:
            wrapped = Cell(name=f"{self._name}.{key}.transformed", value=None, jepa=lambda inputs, t=transform: t(inputs[key].value) if key in inputs else None)
            wrapped._inputs[key] = other
            other._outputs[wrapped._name] = wrapped
            self._inputs[key] = wrapped
            wrapped._outputs[self._name] = self
        else:
            self._inputs[key] = other
            other._outputs[self._name] = self
        return self

    def connect_to(self, other: "Cell", name: Optional[str] = None) -> "Cell":
        """Z_out: this cell sends to `other`."""
        return other.connect_from(self, name=name)

    # -- JEPA ---------------------------------------------------------------

    def predict(self) -> Any:
        """JEPA: predict the next value from current inputs."""
        inputs = {k: c.value for k, c in self._inputs.items()}
        return self._jepa(inputs)

    def observe(self, actual: Any) -> float:
        """JEPA: observe the actual value, compute error, return it."""
        predicted = self.predict()
        if isinstance(predicted, (int, float)) and isinstance(actual, (int, float)):
            err = actual - predicted
            self._vibe = self._vibe.nudge(target_pos=(float(actual),))
            return err
        return 0.0

    def tick(self) -> None:
        """One update cycle. Read inputs, run JEPA, write value, step vibe."""
        # DoubleEntry: snapshot before
        self._debit = self._credit
        # JEPA: predict from inputs
        predicted = self.predict()
        # If no inputs, just hold
        if predicted is not None:
            self._credit = predicted
        self._value = self._credit
        # Vibe: step
        self._vibe = self._vibe.step(dt=1.0)
        # Murmur: tick the heartbeat
        self.murmur()
        # Tick counter
        self._ticks += 1
        # Log
        self._log.append({
            "tick": self._ticks,
            "value": self._value,
            "vibe": (self._vibe.pos, self._vibe.vel, self._vibe.acc),
            "gc_phase": self._gc_phase,
            "t": time.time(),
        })

    # -- Vibe ---------------------------------------------------------------

    @property
    def vibe(self) -> Vibe:
        return self._vibe

    @vibe.setter
    def vibe(self, v: Vibe) -> None:
        self._vibe = v

    # -- GC -----------------------------------------------------------------

    def gc(self) -> str:
        """3-phase garbage collection. Returns the phase run."""
        if self._gc_phase == 0:
            # Phase 0: merge similar. If two outputs are too similar, mark for merge.
            seen = {}
            for name, c in list(self._outputs.items()):
                sig = repr(c.value)[:50]
                if sig in seen:
                    # merge
                    other = seen[sig]
                    self._outputs.pop(name)
                else:
                    seen[sig] = c
            self._gc_phase = 1
            return "merge-similar"
        elif self._gc_phase == 1:
            # Phase 1: decay old. Inputs that haven't murmured in 60s are weak.
            now = time.time()
            for name, c in list(self._inputs.items()):
                if now - c.last_murmur > 60:
                    self._inputs.pop(name, None)
            self._gc_phase = 2
            return "decay-old"
        else:
            # Phase 2: prune weak. Connections with low value get pruned.
            self._gc_phase = 0
            return "prune-weak"

    # -- Murmur -------------------------------------------------------------

    def murmur(self) -> bool:
        """Heartbeat. Returns True if still alive."""
        self._last_murmur = time.time()
        self._murmur_count += 1
        return True

    # -- Graph --------------------------------------------------------------

    def neighbors(self) -> List["Cell"]:
        """Cells directly connected (in or out)."""
        return list(self._inputs.values()) + list(self._outputs.values())

    def reach(self, max_depth: int = 3) -> List["Cell"]:
        """All cells reachable within max_depth hops (0 = just this cell)."""
        seen: List[Cell] = [self]
        seen_ids: set = {id(self)}
        frontier = [self]
        for _ in range(max_depth):
            next_frontier = []
            for c in frontier:
                for n in c.neighbors():
                    if id(n) not in seen_ids:
                        seen_ids.add(id(n))
                        next_frontier.append(n)
                        seen.append(n)
            frontier = next_frontier
        return seen

    def path_to(self, target: "Cell", max_depth: int = 10) -> Optional[List["Cell"]]:
        """Shortest path from this cell to target, or None."""
        if self is target:
            return [self]
        seen = {id(self)}
        frontier = [(self, [self])]
        for _ in range(max_depth):
            next_frontier = []
            for c, path in frontier:
                for n in c.neighbors():
                    if n is target:
                        return path + [n]
                    if id(n) not in seen:
                        seen.add(id(n))
                        next_frontier.append((n, path + [n]))
            frontier = next_frontier
        return None

    # -- Properties ---------------------------------------------------------

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, v: Any) -> None:
        self._debit = self._credit
        self._credit = v
        self._value = v

    @property
    def name(self) -> str:
        return self._name

    @property
    def address(self) -> str:
        return self._address

    @property
    def inputs(self) -> Dict[str, "Cell"]:
        return dict(self._inputs)

    @property
    def outputs(self) -> Dict[str, "Cell"]:
        return dict(self._outputs)

    @property
    def debit(self) -> Any:
        return self._debit

    @property
    def credit(self) -> Any:
        return self._credit

    @property
    def age(self) -> float:
        return time.time() - self._born

    @property
    def ticks(self) -> int:
        return self._ticks

    @property
    def last_murmur(self) -> float:
        return self._last_murmur

    @property
    def log(self) -> List[Dict[str, Any]]:
        return list(self._log)

    def __repr__(self) -> str:
        return f"Cell({self._name}, value={self._value!r}, ticks={self._ticks})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "address": self._address,
            "value": self._value,
            "vibe": {"pos": self._vibe.pos, "vel": self._vibe.vel, "acc": self._vibe.acc},
            "ticks": self._ticks,
            "age": self.age,
            "inputs": {k: c._address for k, c in self._inputs.items()},
            "outputs": {k: c._address for k, c in self._outputs.items()},
        }


# -- The Graph -------------------------------------------------------------

class Graph:
    """A collection of cells. The graph is the truth."""

    def __init__(self, cells: Optional[List[Cell]] = None):
        self._cells: Dict[str, Cell] = {}
        if cells:
            for c in cells:
                self.add(c)

    def add(self, cell: Cell) -> "Graph":
        self._cells[cell.address] = cell
        return self

    def get(self, address: str) -> Optional[Cell]:
        return self._cells.get(address)

    def all_cells(self) -> List[Cell]:
        return list(self._cells.values())

    def tick(self, n: int = 1) -> None:
        """Tick all cells n times. Topological order would be ideal; we do a simple passes approach."""
        for _ in range(n):
            for c in self._cells.values():
                c.tick()

    def gc_all(self) -> List[str]:
        """Run GC on all cells. Returns a log of phases."""
        log = []
        for c in self._cells.values():
            log.append(f"{c.name}: {c.gc()}")
        return log

    def murmur_all(self) -> int:
        """Heartbeat all cells. Returns the count."""
        n = 0
        for c in self._cells.values():
            if c.murmur():
                n += 1
        return n

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cells": [c.to_dict() for c in self._cells.values()],
            "n_cells": len(self._cells),
            "t": time.time(),
        }

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)

    def __len__(self) -> int:
        return len(self._cells)

    def __repr__(self) -> str:
        return f"Graph({len(self._cells)} cells)"


# -- CLI -------------------------------------------------------------------

def _cli():
    import argparse
    p = argparse.ArgumentParser(prog="cell-runtime", description="The 8-primitive cell as a working CLI.")
    sub = p.add_subparsers(dest="cmd")

    demo = sub.add_parser("demo", help="Run a small demo: three cells wired together.")
    demo.add_argument("--ticks", type=int, default=10)

    info = sub.add_parser("info", help="Print the 8 primitives.")

    args = p.parse_args()

    if args.cmd == "demo":
        a = Cell(value=1.0, name="a")
        b = Cell(value=2.0, name="b")
        c = Cell(value=0.0, name="c", jepa=lambda inputs: sum(v for v in inputs.values() if isinstance(v, (int, float))))
        c.connect_from(a)
        c.connect_from(b)
        g = Graph([a, b, c])
        for i in range(args.ticks):
            g.tick()
            print(f"tick {i+1}: a={a.value}, b={b.value}, c={c.value}")
        print()
        print("Final graph:")
        for cell in g.all_cells():
            print(f"  {cell}")
    elif args.cmd == "info":
        print("The 8 primitives of a Cell:")
        print("  Z_in       — inputs (other cells)")
        print("  Z_out      — outputs (other cells)")
        print("  JEPA       — predictive update")
        print("  DoubleEntry — paired state (debit/credit)")
        print("  Vibe       — position/velocity/acceleration")
        print("  GC         — 3-phase garbage collection")
        print("  Murmur     — heartbeat (low-cost 'I am here')")
        print("  Graph      — place in the whole")
    else:
        p.print_help()


if __name__ == "__main__":
    _cli()
