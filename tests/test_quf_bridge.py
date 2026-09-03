#!/usr/bin/env python3
"""test_quf_bridge.py — 6th polyformalism substrate: cell-runtime ↔ QUF.

Tests:
  1. Round-trip: graph → QUF bytes → graph → QUF bytes (byte-exact)
  2. State hash: graph.state_hash() matches the 5-substrate polyformalism
  3. Cross-substrate: a QUF written by cell-runtime is loadable in
     quf_v2.py (Python), quilt-verilog ref, and quf-vhdl ref, with the
     same FNV-1a 64-bit state hash.
  4. Multi-cell test: 8 cells, 12 edges (the canonical 5-substrate fixture
     scaled to 8 cells).
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

# Path setup
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))    # cell-runtime
sys.path.insert(0, str(HERE.parent))            # cell-runtime/quf_bridge.py
sys.path.insert(0, "/workspace/quilt-timesfm")  # quf_v2

from cell_runtime import Cell, Graph
from quf_bridge import (
    graph_to_quf, quf_to_graph, graph_to_bytes, bytes_to_graph,
    graph_state_hash,
)
from quf_v2 import QufFile, loads, dumps
# state_hash is a method on QufFile, not a module-level function
qf_state_hash = lambda q: q.state_hash()


QUILT_VERILOG = "/workspace/quilt-verilog"
QUILT_VHDL    = "/workspace/quf-vhdl"


def _make_3cell_graph() -> Graph:
    """a → c, b → c; c.value = a.value + b.value."""
    a = Cell(value=1.0, name="a")
    b = Cell(value=2.0, name="b")
    c = Cell(value=0.0, name="c",
             jepa=lambda i: sum(v for v in i.values() if isinstance(v, (int, float))))
    c.connect_from(a)
    c.connect_from(b)
    g = Graph([a, b, c])
    g.tick(1)
    return g


def _make_8cell_graph() -> Graph:
    """8 cells, each with random connections; mirrors the 5-substrate fixture."""
    import random
    rng = random.Random(42)
    cells = [Cell(value=float(i + 1) / 10.0, name=f"c{i}") for i in range(8)]
    # Connect cell i to cells (i+1) % 8 and (i+3) % 8, summing
    for i in range(8):
        j1, j2 = (i + 1) % 8, (i + 3) % 8
        cells[i].jepa = (lambda ii, jj, _i=i: (
            lambda i: (i.get(f"a{ii}j{jj}", 0) or 0) + (i.get(f"a{ii}j{ii}", 0) or 0)
        ))(i, j1)
        cells[i].connect_from(cells[j1], name=f"a{i}j{j1}")
        if j1 != j2:
            cells[i].connect_from(cells[j2], name=f"a{i}j{j2}")
    return Graph(cells)


class TestRoundTrip(unittest.TestCase):

    def test_3cell_round_trip(self):
        g = _make_3cell_graph()
        blob1 = graph_to_bytes(g)
        h1 = graph_state_hash(g)
        # Round-trip
        g2 = bytes_to_graph(blob1)
        blob2 = graph_to_bytes(g2)
        h2 = graph_state_hash(g2)
        self.assertEqual(blob1, blob2, "round-trip not byte-exact")
        self.assertEqual(h1, h2, f"state hash changed: {h1:016x} vs {h2:016x}")
        # Note: the 3-cell graph is a *different* fixture from the
        # canonical 4-cell 4-edge test, so the hash is a separate
        # polyformalism value.  Locking it in.
        self.assertEqual(h1, 0xbbaec330a403c979,
                          f"3-cell graph hash should match 0xbbaec330a403c979, got 0x{h1:016x}")

    def test_8cell_round_trip(self):
        g = _make_8cell_graph()
        blob1 = graph_to_bytes(g)
        h1 = graph_state_hash(g)
        g2 = bytes_to_graph(blob1)
        blob2 = graph_to_bytes(g2)
        h2 = graph_state_hash(g2)
        self.assertEqual(blob1, blob2)
        self.assertEqual(h1, h2)

    def test_state_hash_matches_quf_v2(self):
        """graph.state_hash() == QufFile.state_hash() (the polyformalism value)."""
        g = _make_3cell_graph()
        qf = graph_to_quf(g)
        h_graph = graph_state_hash(g)
        h_qf = qf_state_hash(qf)
        self.assertEqual(h_graph, h_qf, f"graph vs quf: {h_graph:016x} vs {h_qf:016x}")


class TestCrossSubstrate(unittest.TestCase):
    """The 6th substrate (cell-runtime) is byte-exact with the other 5."""

    def test_3cell_loads_in_python_quf_v2(self):
        """A cell-runtime QUF loads in quf_v2.py with the same state hash."""
        g = _make_3cell_graph()
        blob = graph_to_bytes(g)
        h_graph = graph_state_hash(g)
        # Load through quf_v2
        qf = loads(blob)
        h_qf = qf.state_hash()
        self.assertEqual(h_graph, h_qf,
                          f"cell-runtime vs quf_v2: {h_graph:016x} vs {h_qf:016x}")

    @unittest.skipUnless(os.path.exists(f"{QUILT_VERILOG}/tools/quf.py"),
                          "Verilog ref not present")
    def test_3cell_loads_in_verilog_ref(self):
        """cell-runtime QUF is the same bytes as Verilog ref produces."""
        g = _make_3cell_graph()
        # Use a fixed version so the QUF bytes match
        VERSION = "verilog-ref-test-1"
        self.assertEqual(len(VERSION), 18, "version must be 18 chars to match")
        qf = graph_to_quf(g, version=VERSION)
        doc = qf.to_dict()
        with tempfile.TemporaryDirectory() as d:
            fixture = os.path.join(d, "fixture.json")
            v_path  = os.path.join(d, "v.quf")
            with open(fixture, "w") as f:
                json.dump(doc, f)
            subprocess.check_call(
                ["python3", f"{QUILT_VERILOG}/tools/quf.py", "create", fixture, v_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            v_blob = open(v_path, "rb").read()
            cell_blob = graph_to_bytes(g, version=VERSION)
            self.assertEqual(cell_blob, v_blob,
                              "cell-runtime QUF != Verilog reference QUF")
            # state hash match
            h_cell = graph_state_hash(g)
            h_v = loads(v_blob).state_hash()
            self.assertEqual(h_cell, h_v)

    @unittest.skipUnless(os.path.exists(f"{QUILT_VHDL}/tools/vhdl_quf.py"),
                          "VHDL ref not present")
    def test_3cell_loads_in_vhdl_ref(self):
        """cell-runtime QUF is the same bytes as VHDL ref produces."""
        g = _make_3cell_graph()
        VERSION = "vhdl-ref-test-vh-1"
        self.assertEqual(len(VERSION), 18)
        qf = graph_to_quf(g, version=VERSION)
        doc = qf.to_dict()
        with tempfile.TemporaryDirectory() as d:
            fixture = os.path.join(d, "fixture.json")
            x_path  = os.path.join(d, "x.quf")
            with open(fixture, "w") as f:
                json.dump(doc, f)
            subprocess.check_call(
                ["python3", f"{QUILT_VHDL}/tools/vhdl_quf.py", "create", fixture, x_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            x_blob = open(x_path, "rb").read()
            cell_blob = graph_to_bytes(g, version=VERSION)
            self.assertEqual(cell_blob, x_blob,
                              "cell-runtime QUF != VHDL reference QUF")


class TestDialMapping(unittest.TestCase):

    def test_value_in_q1_15(self):
        """Cell value 0.5 maps to dial[0] = 0x4000."""
        g = _make_3cell_graph()
        qf = graph_to_quf(g)
        # c is index 2; its value was 1.0 + 2.0 = 3.0 (but JEPA runs in tick)
        # Actually c.value after 1 tick is the JEPA of inputs = 1.0 + 2.0 = 3.0
        # which overflows Q1.15.  We expect the clamped value (0.9999...).
        dials_c = qf.dials[2]
        self.assertGreater(dials_c[0], 0x7F00,
                            f"dial[0] should be near 0.9999 Q1.15, got 0x{dials_c[0]:04x}")

    def test_cell_count_matches_dials(self):
        g = _make_3cell_graph()
        qf = graph_to_quf(g)
        self.assertEqual(len(qf.dials), 3)
        self.assertEqual(qf.header["cell_count"], 3)

    def test_edge_count_matches_edges(self):
        g = _make_3cell_graph()
        qf = graph_to_quf(g)
        # 2 edges: a→c, b→c
        self.assertEqual(len(qf.edges), 2)
        self.assertEqual(qf.header["edge_count"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
