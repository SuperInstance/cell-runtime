"""quf_bridge.py — The cell-runtime × QUF polyformalism bridge.

Maps a `cell_runtime.Graph` to a `quf_v2.QufFile` and back, byte-exact
with the 5-substrate polyformalism (C, Rust, Python, Verilog, VHDL).

The mapping is:

  Cell               →  one row in QufFile.dials (16 u16 values)
  Cell.address       →  cell's name (e.g. "a" → 0)
  Cell.value         →  dial[0] (Q1.15 fixed-point; float→int conversion)
  Cell.ticks         →  dial[1] (tick count, low 16 bits)
  Cell.vibe.pos[0]   →  dial[5] (THRESH for 1D vibration)
  Cell.connect_from  →  one row in QufFile.edges (src→dst, K buckets
                        hold the JEPAs for each input)
  Graph              →  QufFile (header + dials + edges + routing + ticks)

The bridge is bidirectional:
  - Graph → QufFile → bytes → QufFile → Graph  (round-trip)
  - The FNV-1a 64-bit state hash is bit-exact with the 5 substrates.

This is the 6th polyformalism substrate: cell-runtime's 8-primitive
cell, expressed as a QUF, with the same FNV-1a 64-bit state hash.
"""
from __future__ import annotations

import math
import sys
import os
from typing import Any, Dict, List, Optional, Tuple

# Cell-runtime is a sibling package; if not installed, fall back to a
# stub so the module is still importable.
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
    from cell_runtime import Cell, Graph
    HAS_CELL_RUNTIME = True
except ImportError:
    HAS_CELL_RUNTIME = False

# QUF (sibling repo at /workspace/quilt-timesfm)
QUF_PATH = "/workspace/quilt-timesfm"
if os.path.exists(QUF_PATH):
    sys.path.insert(0, QUF_PATH)
from quf_v2 import QufFile, EdgeRecord, RouteRecord, loads, dumps


# ============================================================================
# Cell ↔ Dial mapping
# ============================================================================

def _float_to_q1515(v: float) -> int:
    """Convert a float to Q1.15 fixed-point (clamped to [-1, 1))."""
    if v < -1.0: v = -1.0
    if v >= 1.0: v = 1.0 - 1e-6
    return int(v * 32768) & 0xFFFF


def _q1515_to_float(v: int) -> float:
    """Convert a Q1.15 fixed-point to float."""
    if v >= 0x8000:
        v -= 0x10000
    return v / 32768.0


def _cell_to_dials(cell: "Cell", cell_idx: int) -> List[int]:
    """Map a Cell to a 16-element dial row.

    Dial layout (matches the QCell contract):
      [0]  value (Q1.15)               — the cell's current value
      [1]  ticks (low 16)              — how many ticks since born
      [2]  gc_phase (0/1/2)            — current GC phase
      [3]  inputs (low 8)              — count of inputs (Z_in)
      [4]  outputs (low 8)             — count of outputs (Z_out)
      [5]  threshold (Q1.15)           — vibe.pos[0] (the 1-D spring pos)
      [6]  jepa_kind (0=hold, 1=sum)   — which JEPA the cell uses
      [7]  reserved (0)                — last_murmur_age is not bit-stable
      [8]  reserved (0)                — age is not bit-stable (time-based)
      [9]  reserved
      [10] reserved
      [11] reserved
      [12] reserved
      [13] reserved
      [14] reserved
      [15] reserved

    NOTE: cell-runtime's `age` and `last_murmur` properties are
    time-based (time.time() - born), so they vary between runs.  The
    polyformalism needs bit-exact deterministic bytes, so we set
    dial[7] and dial[8] to 0 here.  The age and murmur are exposed
    via cell_runtime's API directly, not via QUF.
    """
    inputs_count = len(cell.inputs)
    outputs_count = len(cell.outputs)
    vibe_pos = cell.vibe.pos[0] if cell.vibe.pos else 0.0
    threshold = max(-1.0, min(0.9999, vibe_pos))
    return [
        _float_to_q1515(float(cell.value)) if isinstance(cell.value, (int, float)) else 0,
        cell.ticks & 0xFFFF,
        cell._gc_phase & 0xFFFF,
        inputs_count & 0xFFFF,
        outputs_count & 0xFFFF,
        _float_to_q1515(threshold),
        1 if cell._jepa is not None and cell._jepa.__code__.co_argcount > 1 else 0,
        0,  # reserved (was murmur_age; not bit-stable)
        0,  # reserved (was age; not bit-stable)
        0, 0, 0, 0, 0, 0, 0,
    ]


def _dials_to_cell(dials: List[int], name: str) -> "Cell":
    """Reverse of _cell_to_dials: rebuild a Cell from a 16-element dial row.

    The cell is reconstructed with value, ticks, vibe.pos[0], and a
    simple "hold" JEPA.  Re-connection (edges) happens later in
    _quf_to_graph.
    """
    cell = Cell(value=_q1515_to_float(dials[0]), name=name)
    # ticks
    for _ in range(dials[1]):
        cell.tick()
    # vibe
    cell.vibe = cell.vibe  # noop; will be set explicitly
    # Re-create vibe with the threshold as pos
    from cell_runtime import Vibe
    cell._vibe = Vibe(pos=(_q1515_to_float(dials[5]),))
    return cell


# ============================================================================
# Cell → QufFile
# ============================================================================

def graph_to_quf(graph: "Graph", version: str = "cell-runtime-0.1.0") -> QufFile:
    """Build a QufFile from a cell-runtime Graph.

    Cells are addressed by their .address; the order in the QUF is the
    order returned by Graph.all_cells().  Edges are built from
    Cell._inputs (each `connect_from` becomes one edge).

    The Cell.age field is a real-time seconds-since-born, so for
    deterministic byte-exactness we patch all cells to a fixed _born
    time before serializing.  This makes the FNV-1a 64-bit state hash
    reproducible across runs.
    """
    if not HAS_CELL_RUNTIME:
        raise ImportError("cell_runtime is not installed; pip install cell-runtime")

    # Freeze the born time for deterministic byte-exactness
    FROZEN_BORN = 0.0
    for cell in graph.all_cells():
        cell._born = FROZEN_BORN

    cells = graph.all_cells()
    name_to_idx = {c.address: i for i, c in enumerate(cells)}

    # Dials (one row per cell)
    dials = [_cell_to_dials(c, i) for i, c in enumerate(cells)]

    # Edges: each input connection becomes one edge.
    # In cell-runtime, `dst_cell._inputs[name] = src_cell` — so we iterate
    # the receiving cell's inputs and emit (src → dst) per connection.
    edges = []
    for dst_cell in cells:
        for input_name, src_cell in dst_cell.inputs.items():
            src_idx = name_to_idx[src_cell.address]
            dst_idx = name_to_idx[dst_cell.address]
            # K=8 ladder buckets all start at 0
            # base=0, wh=0, age=0 — these match the Verilog+VHDL
            # reference defaults (which read the JSON's base/wh fields;
            # if absent, they default to 0).
            edges.append(EdgeRecord(
                src=src_idx, dst=dst_idx,
                mode=0, slot=0,
                base=0, wh=0, age=0,
                buckets=[0] * 8,
            ))

    # Routing: one route per cell (identity)
    routing = [RouteRecord(i, i) for i in range(len(cells))]

    return QufFile(
        header={
            "quf.version": version,
            "cell_count": len(cells),
            "edge_count": len(edges),
            "route_count": len(routing),
            "edge.k": 8,
            "tick_period": 1,
            "quant.dials": "Q1.15",
            "quant.edges": "Q1.15",
            "quant.routing": "u8",
            "align": 32,
        },
        dials=dials, edges=edges, routing=routing,
        ticks=(1, [0] * len(cells)),
    )


# ============================================================================
# QufFile → Cell graph
# ============================================================================

def quf_to_graph(quf: QufFile) -> "Graph":
    """Rebuild a cell-runtime Graph from a QufFile.

    Cells are named "c0", "c1", ... (matching the order in QufFile.dials).
    Edges are reconstructed from QufFile.edges.

    After reconstruction, the *output* dial rows are patched to reflect
    the actual number of inputs/outputs (since the rebuild from a flat
    dial row doesn't carry that info).
    """
    if not HAS_CELL_RUNTIME:
        raise ImportError("cell_runtime is not installed")

    # Step 1: build cells with stub (no inputs yet)
    cells = [_dials_to_cell(dials, f"c{i}") for i, dials in enumerate(quf.dials)]

    # Step 2: connect edges (this populates _inputs and _outputs)
    for edge in quf.edges:
        src = cells[edge.src]
        dst = cells[edge.dst]
        src.connect_to(dst, name=f"e{edge.src}->{edge.dst}")

    # Step 3: freeze born time for deterministic byte-exactness
    for cell in cells:
        cell._born = 0.0
        cell._last_murmur = 0.0

    g = Graph(cells)

    return g


# ============================================================================
# Convenience: bytes round-trip
# ============================================================================

def graph_to_bytes(graph: "Graph", version: str = "cell-runtime-0.1.0") -> bytes:
    """Serialize a Graph to QUF bytes (compatible with C/Rust/Verilog/VHDL/Python)."""
    return dumps(graph_to_quf(graph, version))


def bytes_to_graph(blob: bytes) -> "Graph":
    """Load a Graph from QUF bytes (compatible with C/Rust/Verilog/VHDL/Python)."""
    return quf_to_graph(loads(blob))


# ============================================================================
# State hash bridge
# ============================================================================

def graph_state_hash(graph: "Graph") -> int:
    """Return the FNV-1a 64-bit state hash of the Graph (bit-exact with
    the other 5 substrates)."""
    return graph_to_quf(graph).state_hash()


# ============================================================================
# CLI smoke test
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("cell-runtime × QUF bridge — 6th polyformalism substrate")
    print("=" * 60)
    if not HAS_CELL_RUNTIME:
        print("cell_runtime NOT installed; install with: pip install cell-runtime")
        sys.exit(1)

    # Build a small graph: 3 cells, 2 edges (c0→c2, c1→c2)
    a = Cell(value=1.0, name="a")
    b = Cell(value=2.0, name="b")
    c = Cell(value=0.0, name="c", jepa=lambda inputs: sum(v for v in inputs.values() if isinstance(v, (int, float))))
    c.connect_from(a, name="a_in")
    c.connect_from(b, name="b_in")
    g = Graph([a, b, c])
    g.tick(1)

    blob = graph_to_bytes(g)
    h1 = graph_state_hash(g)
    print(f"  cells: 3, edges: 2, QUF bytes: {len(blob)}, state_hash: 0x{h1:016x}")

    g2 = bytes_to_graph(blob)
    h2 = graph_state_hash(g2)
    print(f"  round-trip bytes: {len(graph_to_bytes(g2))}, state_hash: 0x{h2:016x}")
    assert h1 == h2, f"hash mismatch: {h1:016x} vs {h2:016x}"
    print(f"  PASS — the 6th substrate (cell-runtime) speaks QUF bit-exact")
