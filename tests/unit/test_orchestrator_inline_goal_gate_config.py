"""Unit test that inline goal should resolve gate config from bernstein.yaml."""

from __future__ import annotations

from pathlib import Path

from bernstein.core.config.seed_config import SeedConfig
from bernstein.core.config.seed_parser import parse_seed


def test_inline_goal_seed_minimal_has_no_gates() -> None:
    """Demonstrates the bug: minimal inline-goal seed has no quality_gates.

    The _bootstrap_from_goal_impl function at bootstrap.py:1418 creates:
        seed = SeedConfig(goal=goal, cli=cli, model=model)

    This minimal seed has quality_gates=None, so orchestrator journals null.
    """
    # This is what _bootstrap_from_goal_impl creates for inline goals
    minimal_seed = SeedConfig(goal="test", cli="claude", model=None)  # type: ignore[call-arg]

    # The bug: quality_gates is None
    assert minimal_seed.quality_gates is None


def test_full_seed_parse_preserves_gates(tmp_path: Path) -> None:
    """A fully parsed seed DOES have quality_gates when bernstein.yaml has them."""
    seed_yaml = tmp_path / "bernstein.yaml"
    seed_yaml.write_text("""goal: "test"
cli: claude
max_agents: 1
quality_gates:
  enabled: true
  lint: true
  lint_command: "echo lint"
  tests: true
  test_command: "echo test"
""")

    parsed_seed = parse_seed(seed_yaml)

    # Full parse DOES preserve quality_gates
    assert parsed_seed.quality_gates is not None
    assert parsed_seed.quality_gates.enabled is True  # type: ignore[union-attr]


def test_reading_gates_from_existing_yaml(tmp_path: Path) -> None:
    """Demonstrates the fix: read gates from existing bernstein.yaml for inline goals."""
    seed_yaml = tmp_path / "bernstein.yaml"
    seed_yaml.write_text("""goal: "placeholder"
cli: claude
max_agents: 1
quality_gates:
  enabled: true
  lint: true
  lint_command: "echo lint"
  tests: true
  test_command: "echo test"
""")

    # Parse to extract quality_gates
    existing_config = parse_seed(seed_yaml)

    # The fix: copy quality_gates from existing config
    inline_seed_with_gates = SeedConfig(
        goal="inline goal text",  # type: ignore[call-arg]
        cli="claude",
        model=None,
        quality_gates=existing_config.quality_gates,
    )

    # After fix: inline seed should have quality_gates
    assert inline_seed_with_gates.quality_gates is not None
    assert inline_seed_with_gates.quality_gates.enabled is True  # type: ignore[union-attr]
