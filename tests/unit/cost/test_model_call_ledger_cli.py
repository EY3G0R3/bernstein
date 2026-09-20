"""Tests for ModelCallLedger CLI commands - CLI invocation layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from bernstein.cli.commands.cost import cost_cmd
from bernstein.core.cost.model_call_ledger import ModelCallLedger

# --- Fixtures ---


@pytest.fixture()
def sdd_dir(tmp_path: Path) -> Path:
    """Return a temporary .sdd directory."""
    sdd = tmp_path / ".sdd"
    sdd.mkdir()
    (sdd / "runtime").mkdir()
    return sdd


@pytest.fixture()
def ledger(sdd_dir: Path) -> ModelCallLedger:
    """Return a fresh ledger instance."""
    return ModelCallLedger(sdd_dir)


@pytest.fixture()
def runner() -> CliRunner:
    """Return a Click CLI test runner."""
    return CliRunner()


# --- Tests ---


def test_cli_reuse_identical_flag_short_circuits(
    ledger: ModelCallLedger,
    sdd_dir: Path,
    runner: CliRunner,
) -> None:
    """The --reuse-identical flag short-circuits on matching content hash."""
    # Arrange: write one succeeded record to the ledger
    call_count = 0

    def mock_call() -> str:
        nonlocal call_count
        call_count += 1
        return "output text"

    first = ledger.invoke(
        capability_id="test-cap",
        adapter_id="test-adapter",
        model="test-model",
        call=mock_call,
        input_text="input text",
        parameters={"key": "value"},
    )
    assert call_count == 1
    assert first.status == "succeeded"

    # Act: invoke via CLI with --reuse-identical and the same input
    result = runner.invoke(
        cost_cmd,
        [
            "model-call",
            "invoke",
            "--sdd-dir",
            str(sdd_dir),
            "--capability-id",
            "test-cap",
            "--adapter-id",
            "test-adapter",
            "--model",
            "test-model",
            "--input",
            "input text",
            "--parameters",
            json.dumps({"key": "value"}),
            "--reuse-identical",
        ],
    )

    # Assert: CLI succeeded, adapter was NOT called again
    assert result.exit_code == 0, result.output
    # The CLI should report reuse
    assert "reused" in result.output.lower() or first.id in result.output
    # Read back from ledger - create fresh instance to force reload from disk
    fresh_ledger = ModelCallLedger(sdd_dir)
    records = fresh_ledger.list_records(limit=10)
    assert len(records) == 2  # first + reused
    reused = records[1]
    assert reused.reused_from == first.id
    assert reused.output_text == first.output_text


def test_cli_replay_record_id(
    ledger: ModelCallLedger,
    sdd_dir: Path,
    runner: CliRunner,
) -> None:
    """The replay subcommand re-executes a stored call and writes a new linked record."""
    # Arrange: write one record
    original = ledger.invoke(
        capability_id="test-cap",
        adapter_id="test-adapter",
        model="test-model",
        call=lambda: "first output",
        input_text="input text",
        parameters={"key": "value"},
    )
    assert original.output_text == "first output"

    # Act: replay via CLI
    result = runner.invoke(
        cost_cmd,
        [
            "model-call",
            "replay",
            "--sdd-dir",
            str(sdd_dir),
            "--record-id",
            original.id,
        ],
    )

    # Assert: CLI succeeded, new record written
    assert result.exit_code == 0, result.output
    # Read back from ledger - create fresh instance to force reload from disk
    fresh_ledger = ModelCallLedger(sdd_dir)
    records = fresh_ledger.list_records(limit=10)
    assert len(records) == 2
    replayed = records[1]
    assert replayed.replay_of == original.id
    # CLI uses mock adapter that returns fixed string
    assert replayed.output_text == "Replayed output for test-model"
    assert replayed.id != original.id
    # Original is untouched
    original_refreshed = fresh_ledger.get_record(original.id)
    assert original_refreshed is not None
    assert original_refreshed.output_text == "first output"
