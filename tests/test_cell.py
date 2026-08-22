"""Tests for cell_runtime."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cell_runtime import Cell, Graph, Vibe


def test_basic_value():
    c = Cell(value=42, name="test")
    assert c.value == 42
    assert c.name == "test"
    assert c.ticks == 0


def test_tick_holds():
    c = Cell(value=10, name="t")
    c.tick()
    assert c.value == 10
    assert c.ticks == 1


def test_wired_sum():
    a = Cell(value=1.0, name="a")
    b = Cell(value=2.0, name="b")
    c = Cell(value=0.0, name="c", jepa=lambda inputs: sum(v for v in inputs.values() if isinstance(v, (int, float))))
    c.connect_from(a)
    c.connect_from(b)
    g = Graph([a, b, c])
    for _ in range(3):
        g.tick()
    assert c.value == 3.0


def test_murmur():
    c = Cell(value=1, name="m")
    assert c.murmur() is True
    assert c.last_murmur > 0
    assert c._murmur_count == 1


def test_double_entry():
    c = Cell(value=10, name="de")
    c.value = 20
    assert c.debit == 10
    assert c.credit == 20


def test_vibe_step():
    v = Vibe(pos=(0.0,), vel=(1.0,), acc=(0.5,))
    v2 = v.step(dt=2.0)
    assert v2.pos[0] == 0.0 + 1.0 * 2.0 + 0.5 * 0.5 * 4.0  # 0 + 2 + 1 = 3
    assert v2.vel[0] == 1.0 + 0.5 * 2.0  # 1 + 1 = 2


def test_vibe_nudge():
    v = Vibe(pos=(0.0,), vel=(0.0,), acc=(0.0,))
    v2 = v.nudge(target_pos=(10.0,))
    assert v2.acc[0] == 1.0  # k=0.1 * (10-0)


def test_graph_tick():
    cells = [Cell(value=i, name=f"c{i}") for i in range(5)]
    g = Graph(cells)
    g.tick(3)
    for c in cells:
        assert c.ticks == 3


def test_reach():
    a = Cell(value=1, name="a")
    b = Cell(value=2, name="b")
    c = Cell(value=3, name="c")
    b.connect_from(a)
    c.connect_from(b)
    reached = a.reach(max_depth=2)
    assert b in reached
    assert c in reached


def test_path_to():
    a = Cell(value=1, name="a")
    b = Cell(value=2, name="b")
    c = Cell(value=3, name="c")
    b.connect_from(a)
    c.connect_from(b)
    path = a.path_to(c)
    assert path is not None
    assert path[0] is a
    assert path[-1] is c


def test_gc_phases():
    c = Cell(value=1, name="gc")
    p0 = c.gc()
    p1 = c.gc()
    p2 = c.gc()
    assert p0 == "merge-similar"
    assert p1 == "decay-old"
    assert p2 == "prune-weak"


def test_address_is_name():
    c = Cell(value=1, name="x")
    assert c.address == "x"


def test_to_dict():
    c = Cell(value=42, name="d")
    d = c.to_dict()
    assert d["name"] == "d"
    assert d["value"] == 42
    assert "vibe" in d


def test_jepa_predict_observe():
    c = Cell(value=10.0, name="j", jepa=lambda inputs: 0.0)
    c.connect_from(Cell(value=5.0, name="x"))
    pred = c.predict()
    err = c.observe(7.0)
    # err = actual - predicted
    assert err == 7.0


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
