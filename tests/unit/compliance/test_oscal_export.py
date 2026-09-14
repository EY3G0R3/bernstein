"""
Tests for the NIST OSCAL assessment-results export (Issue #5456, piece 2).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bernstein.compliance.oscal import (
    build_oscal_assessment_results,
    validate_oscal_assessment_results,
)
from bernstein.eval.bench.bundle import SubmissionBundle
from bernstein.eval.bench.golden_suite import build_golden_suite_v1
from bernstein.eval.bench.runner import BenchRunner, MockReplayAdapter
from bernstein.eval.bench.signer import StubSigner
from bernstein.eval.bench.tool_surface_suite import build_tool_surface_suite

if TYPE_CHECKING:
    from bernstein.eval.bench.suite import BenchSuite


def _signed_bundle(suite: BenchSuite) -> SubmissionBundle:
    runner = BenchRunner(suite=suite, adapter=MockReplayAdapter(), scheduler_config={})
    return StubSigner().sign(runner.run())


@pytest.fixture()
def sample_sdd_with_bundle(tmp_path: Path) -> tuple[Path, SubmissionBundle]:
    sdd = tmp_path / ".sdd"
    audit_dir = sdd / "audit"
    lineage_dir = sdd / "lineage"
    metrics_dir = sdd / "metrics"
    bundles_dir = sdd / "bench" / "bundles"
    audit_dir.mkdir(parents=True, exist_ok=True)
    lineage_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    bundles_dir.mkdir(parents=True, exist_ok=True)

    # Write minimal audit event
    (audit_dir / "events.jsonl").write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00Z", "event_type": "tool_call", "hmac": "abc"}) + "\n",
        encoding="utf-8",
    )

    # Build and sign a bench bundle
    bundle = _signed_bundle(build_golden_suite_v1())

    bundle_file = bundles_dir / f"{bundle.bundle_hash()}.json"
    bundle.save(bundle_file)

    return sdd, bundle


class TestOSCALExport:
    def test_controls_resolve_through_the_bundles_suite_not_only_golden(self) -> None:
        bundle = _signed_bundle(build_tool_surface_suite())
        declared = build_tool_surface_suite().controls
        assert declared
        doc = build_oscal_assessment_results(standard="ai-act", bundles=[bundle])
        by_target = {f["target"]["target-id"]: f for f in doc["assessment-results"]["results"][0]["findings"]}
        for cid in declared:
            assert by_target[cid]["target"]["status"]["state"] in ("satisfied", "not-satisfied"), cid
            assert by_target[cid]["related-observations"], cid
        assert "remarks" not in doc["assessment-results"]["results"][0]

    def test_bundle_from_unknown_suite_is_named_in_remarks(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]
    ) -> None:
        _, bundle = sample_sdd_with_bundle
        raw = bundle.to_dict()
        raw["suite_version"] = "vendor-suite-v9"
        # Re-derive the hash so the bundle is internally consistent.
        unknown = SubmissionBundle(
            suite_hash=raw["suite_hash"],
            suite_version=raw["suite_version"],
            task_results=bundle.task_results,
            scheduler_config=raw["scheduler_config"],
            submitted_at=raw["submitted_at"],
        )
        # The changed suite_version keeps the bundle internally consistent: it
        # round-trips through from_dict without a hash mismatch, so this is a
        # bundle a file loader would accept, not one the test smuggles past a
        # skipped check.
        assert SubmissionBundle.from_dict(unknown.to_dict()).bundle_hash() == unknown.bundle_hash()
        doc = build_oscal_assessment_results(standard="ai-act", bundles=[unknown])
        result = doc["assessment-results"]["results"][0]
        assert "vendor-suite-v9" in result["remarks"]
        # Nothing was mapped, so every finding is the unmeasured shape.
        assert all(not f.get("related-observations") for f in result["findings"])
        assert validate_oscal_assessment_results(doc) is True

    def test_oscal_assessment_results_structure_and_validation(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]
    ) -> None:
        _, bundle = sample_sdd_with_bundle
        oscal_doc = build_oscal_assessment_results(
            standard="ai-act",
            bundles=[bundle],
        )

        assert "assessment-results" in oscal_doc
        results_obj = oscal_doc["assessment-results"]
        assert "metadata" in results_obj
        assert "results" in results_obj
        assert results_obj["metadata"]["oscal-version"] == "1.1.0"

        # Validate with internal schema validator
        assert validate_oscal_assessment_results(oscal_doc) is True

        # Check findings contain control IDs and status
        findings = results_obj["results"][0]["findings"]
        finding_targets = [f["target"]["target-id"] for f in findings]
        assert "CTL-ROB-01" in finding_targets

    def test_findings_carry_the_clause_of_the_requested_standard(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]
    ) -> None:
        from bernstein.compliance.controls import get_default_registry

        _, bundle = sample_sdd_with_bundle
        registry = get_default_registry()
        for standard, key in (("ai-act", "eu_ai_act"), ("iso-42001", "iso_42001"), ("owasp-asi", "owasp_asi")):
            doc = build_oscal_assessment_results(standard=standard, bundles=[bundle])
            findings = doc["assessment-results"]["results"][0]["findings"]
            assert len(findings) == len(registry.list_controls())
            for f in findings:
                control = registry.get(f["target"]["target-id"])
                assert control is not None
                (clause,) = [p["value"] for p in f["props"] if p["name"] == "clause"]
                assert clause == control.references.get(key, "unmapped"), (standard, control.control_id)

    def test_unsupported_standard_is_refused_not_labelled(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]
    ) -> None:
        _, bundle = sample_sdd_with_bundle
        with pytest.raises(ValueError, match="unsupported standard"):
            build_oscal_assessment_results(standard="soc2", bundles=[bundle])

    def test_latest_bundle_by_submitted_at_is_reported_regardless_of_order(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]
    ) -> None:
        _, bundle = sample_sdd_with_bundle
        older = SubmissionBundle(
            suite_hash=bundle.suite_hash,
            suite_version=bundle.suite_version,
            task_results=bundle.task_results,
            scheduler_config=bundle.scheduler_config,
            submitted_at=bundle.submitted_at - 3600,
        )
        for order in ([older, bundle], [bundle, older]):
            doc = build_oscal_assessment_results(standard="ai-act", bundles=order)
            result = doc["assessment-results"]["results"][0]
            (obs,) = [o for o in result["observations"] if "CTL-ROB-01" in o["title"]]
            assert bundle.bundle_hash()[:12] in obs["description"]
            assert obs["collected"].startswith("20")  # the bundle's own time, not the 1970 sentinel

    def test_oscal_export_is_deterministic(self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]) -> None:
        _, bundle = sample_sdd_with_bundle
        doc1 = build_oscal_assessment_results(standard="ai-act", bundles=[bundle])
        doc2 = build_oscal_assessment_results(standard="ai-act", bundles=[bundle])

        json1 = json.dumps(doc1, sort_keys=True, indent=2)
        json2 = json.dumps(doc2, sort_keys=True, indent=2)
        assert json1 == json2

    def test_the_document_dates_track_the_bundle_not_a_frozen_sentinel(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]
    ) -> None:
        """metadata.published/last-modified and the result's start follow the same
        rule the observations' collected does -- the latest bundle's submitted_at --
        so the whole document is content-addressed by one policy, not two."""
        _, bundle = sample_sdd_with_bundle
        meta = build_oscal_assessment_results(standard="ai-act", bundles=[bundle])["assessment-results"]
        expected = datetime.fromtimestamp(float(bundle.submitted_at), tz=UTC).isoformat()
        assert meta["metadata"]["published"] == expected
        assert meta["metadata"]["last-modified"] == expected
        assert meta["results"][0]["start"] == expected

    def test_with_no_bundles_the_dates_fall_back_to_the_epoch(self) -> None:
        meta = build_oscal_assessment_results(standard="ai-act", bundles=[])["assessment-results"]
        assert meta["metadata"]["published"] == "1970-01-01T00:00:00+00:00"
        assert meta["results"][0]["start"] == "1970-01-01T00:00:00+00:00"


class TestOSCALCLI:
    def test_compliance_oscal_stdout(self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]) -> None:
        from click.testing import CliRunner

        from bernstein.cli.commands.compliance_cmd import compliance_group

        sdd, _ = sample_sdd_with_bundle
        workdir = sdd.parent
        runner = CliRunner()
        result = runner.invoke(compliance_group, ["oscal", "--workdir", str(workdir), "--standard", "ai-act"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "assessment-results" in data

    def test_oscal_is_reachable_through_the_installed_entry_point(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]
    ) -> None:
        """Invoke ``bernstein compliance oscal`` the way a user does, not the
        group object directly, so a registration problem cannot hide."""
        from click.testing import CliRunner

        from bernstein.cli.main import cli

        sdd, _ = sample_sdd_with_bundle
        result = CliRunner().invoke(cli, ["compliance", "oscal", "--workdir", str(sdd.parent), "--standard", "ai-act"])
        assert result.exit_code == 0, result.output
        assert validate_oscal_assessment_results(json.loads(result.output)) is True

    def test_oscal_refuses_to_export_over_a_bundle_it_could_not_read(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle]
    ) -> None:
        from click.testing import CliRunner

        from bernstein.cli.commands.compliance_cmd import compliance_group

        sdd, _ = sample_sdd_with_bundle
        (sdd / "bench" / "bundles" / "broken.json").write_text("{", encoding="utf-8")
        result = CliRunner().invoke(compliance_group, ["oscal", "--workdir", str(sdd.parent), "--standard", "ai-act"])
        assert result.exit_code != 0
        assert "broken.json" in result.output
        assert "refusing to export" in result.output

    def test_compliance_oscal_file_output(
        self, sample_sdd_with_bundle: tuple[Path, SubmissionBundle], tmp_path: Path
    ) -> None:
        from click.testing import CliRunner

        from bernstein.cli.commands.compliance_cmd import compliance_group

        sdd, _ = sample_sdd_with_bundle
        workdir = sdd.parent
        out_file = tmp_path / "oscal.json"
        runner = CliRunner()
        result = runner.invoke(
            compliance_group, ["oscal", "--workdir", str(workdir), "--standard", "ai-act", "--out", str(out_file)]
        )
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "assessment-results" in data
