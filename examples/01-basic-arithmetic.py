"""
01-basic-arithmetic.py — Three cells wired to add.

The Quilt cell model: a + b = c. The cell IS the system. The graph IS the truth.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cell_runtime import Cell, Graph


def main():
    a = Cell(value=1.0, name="a")
    b = Cell(value=2.0, name="b")
    c = Cell(
        value=0.0,
        name="c",
        jepa=lambda inputs: sum(v for v in inputs.values() if isinstance(v, (int, float))),
    )
    c.connect_from(a)
    c.connect_from(b)

    g = Graph([a, b, c])

    print("Before any ticks:")
    print(f"  a={a.value}, b={b.value}, c={c.value}")
    print()

    for i in range(5):
        g.tick()
        print(f"After tick {i+1}: a={a.value}, b={b.value}, c={c.value}")

    print()
    print("Cell c reach depth=2:")
    for n in c.reach(max_depth=2):
        print(f"  {n}")
    print()
    print("Murmur all:", g.murmur_all(), "cells still alive")
    print()
    print("Graph as dict:")
    import json
    print(json.dumps(g.to_dict(), indent=2, default=str)[:600] + "...")


if __name__ == "__main__":
    main()
