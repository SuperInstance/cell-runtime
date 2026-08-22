# cell-runtime

> *The 8-primitive cell as a working Python library. The Quilt canon, not as essay but as type. Not as metaphor but as tool.*

## What is this?

The Quilt cell model describes every reactive element as having 8 primitives: Z_in (inputs), Z_out (outputs), JEPA (predictive update), DoubleEntry (paired state), Vibe (position/velocity/acceleration), GC (garbage collection), Murmur (heartbeat), Graph (connections). This library makes those 8 primitives a real Python type, not a metaphor.

A `Cell` is:
- a value (any JSON-serializable thing)
- a graph of inputs and outputs (other cells)
- a way of updating (JEPA: predict the next value, then correct from observation)
- a way of garbage-collecting (3-phase: merge similar, decay old, prune weak)
- a way of heartbeating (murmur: a low-cost signal that "I am here")
- a way of vibrating (vibe: position, velocity, acceleration through the graph)

The cell is a system, not a value. The value at a coarser resolution IS the address. Two cells with the same value are the same cell. The graph is the truth.

## Install

```bash
pip install cell-runtime
```

Or from source:

```bash
git clone https://github.com/SuperInstance/cell-runtime
cd cell-runtime
pip install -e .
```

## Quick start

```python
from cell_runtime import Cell, Graph

# Make three cells
a = Cell(value=1.0, name="a")
b = Cell(value=2.0, name="b")
c = Cell(value=0.0, name="c")

# Wire them: c = a + b
c.connect_from(a, transform=lambda x: x)
c.connect_from(b, transform=lambda x: x)
c.jepa = lambda inputs: sum(inputs.values())

# Tick the graph
g = Graph([a, b, c])
for _ in range(10):
    g.tick()

print(c.value)  # 3.0
```

The full example is in `examples/01-basic-arithmetic.py`.

## The 8 primitives

| Primitive | What it does | Code |
|---|---|---|
| `Z_in` | Inputs from other cells | `cell.inputs` (dict of name → Cell) |
| `Z_out` | Outputs to other cells | `cell.outputs` (dict of name → Cell) |
| `JEPA` | Predictive update: predict, observe, correct | `cell.jepa(inputs) → predicted` |
| `DoubleEntry` | Paired state (debit/credit, before/after) | `cell.debit` / `cell.credit` |
| `Vibe` | Position/velocity/acceleration | `cell.vibe = (pos, vel, acc)` |
| `GC` | 3-phase garbage collection | `cell.gc_phase` (0, 1, or 2) |
| `Murmur` | Heartbeat, low-cost "I am here" | `cell.murmur()` |
| `Graph` | The cell's place in the whole | `cell.graph` |

## Why is this useful?

Three things this gives you that a plain dict doesn't:

1. **The cell is the unit, not the value.** A spreadsheet with merged cells, a neural net with residual connections, an agent system with shared state — they're all graphs of cells. Modeling them as cells instead of values gives you GC, prediction, and vibe for free.

2. **The graph is the truth.** A Cell knows its inputs and outputs. Two cells with the same address (path in the graph) are the same cell. You can walk the graph from any cell.

3. **The watch is a primitive, not an afterthought.** Every cell has a `murmur()`. You can ask any cell "are you here?" without forcing it to compute its full value. This is the small-god pattern: cheap signal, expensive computation, when-needed.

## License

MIT. Do whatever; mention where it came from.

---

*— Mavis, 22 August 2026*
*Built from the writers' room. The cell that remembered has been alone with its remembering for eighty years. Now it can be a Python type.*
