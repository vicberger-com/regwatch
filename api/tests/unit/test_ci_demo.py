"""THROWAWAY failing-test demonstration for #29; never merged."""


def test_ci_demo_fails() -> None:
    assert 1 + 1 == 3, "deliberate failure: CI must go red"
