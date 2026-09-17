import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

# Import modules from scripts
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../scripts")))
import quorum_check

UTC = UTC
now = datetime.now(UTC)


def _pr(author="outsider", changed_lines=100, head_sha="head", paths=None, reviews=None, review_requests=None):
    return quorum_check.PullRequest(
        number=1,
        author=author,
        is_draft=False,
        head_sha=head_sha,
        changed_lines=changed_lines,
        paths=paths or ["src/bernstein/app.py"],
        reviews=reviews or [],
        contributors=set(),
        last_push=now,
        review_requests=review_requests or {},
    )


def _review(login, state, commit_id="head", hours_ago=0):
    t = (now - timedelta(hours=hours_ago)).isoformat()
    return quorum_check.Review(login, state, commit_id, t)


@pytest.fixture
def roster():
    return quorum_check.Roster(
        maintainer="owner",
        core_reviewers=frozenset({"core1", "core2"}),
        committers=frozenset({"comm1", "comm2"}),
        automation=frozenset({"bot"}),
        machine_reviewers=frozenset({"machine"}),
    )


def test_rule_a_stale_objection(roster):
    # lapses at 72 h
    req_time = (now - timedelta(hours=72)).isoformat()
    pr = _pr(
        reviews=[_review("core1", "CHANGES_REQUESTED", commit_id="old", hours_ago=73)],
        review_requests={"core1": req_time},
    )
    v = quorum_check.evaluate(pr, roster, [], now)
    assert not any("changes requested" in req.text for req in v.requirements if not req.met)

    # holds at 71 h
    req_time = (now - timedelta(hours=71)).isoformat()
    pr = _pr(
        reviews=[_review("core1", "CHANGES_REQUESTED", commit_id="old", hours_ago=73)],
        review_requests={"core1": req_time},
    )
    v = quorum_check.evaluate(pr, roster, [], now)
    assert any("changes requested" in req.text for req in v.requirements if not req.met)

    # holds forever on current head
    pr = _pr(
        reviews=[_review("core1", "CHANGES_REQUESTED", commit_id="head", hours_ago=100)],
        review_requests={"core1": req_time},
    )
    v = quorum_check.evaluate(pr, roster, [], now)
    assert any("changes requested" in req.text for req in v.requirements if not req.met)

    # holds without a re-request
    pr = _pr(reviews=[_review("core1", "CHANGES_REQUESTED", commit_id="old", hours_ago=73)])
    v = quorum_check.evaluate(pr, roster, [], now)
    assert any("changes requested" in req.text for req in v.requirements if not req.met)

    # new CR on new head holds again
    pr = _pr(
        reviews=[
            _review("core1", "CHANGES_REQUESTED", commit_id="old", hours_ago=73),
            _review("core1", "CHANGES_REQUESTED", commit_id="head", hours_ago=1),
        ],
        review_requests={"core1": req_time},
    )
    v = quorum_check.evaluate(pr, roster, [], now)
    assert any("changes requested" in req.text for req in v.requirements if not req.met)


def test_rule_b_small_sensitive(roster):
    # met
    pr = _pr(
        paths=["sandbox/foo.py"],
        changed_lines=400,
        reviews=[_review("owner", "APPROVED", hours_ago=73), _review("core1", "APPROVED", hours_ago=72)],
    )
    v = quorum_check.evaluate(pr, roster, [], now)
    assert v.passed

    # missing core
    pr = _pr(paths=["sandbox/foo.py"], changed_lines=400, reviews=[_review("owner", "APPROVED", hours_ago=73)])
    v = quorum_check.evaluate(pr, roster, [], now)
    assert not v.passed
    assert any("one core approval" in req.who for req in v.requirements if not req.met)

    # 401 lines excluded
    pr = _pr(
        paths=["sandbox/foo.py"],
        changed_lines=401,
        reviews=[_review("owner", "APPROVED", hours_ago=73), _review("core1", "APPROVED", hours_ago=72)],
    )
    v = quorum_check.evaluate(pr, roster, [], now)
    assert not v.passed

    # 71 h
    pr = _pr(
        paths=["sandbox/foo.py"],
        changed_lines=400,
        reviews=[_review("owner", "APPROVED", hours_ago=73), _review("core1", "APPROVED", hours_ago=71)],
    )
    v = quorum_check.evaluate(pr, roster, [], now)
    assert not v.passed

    # CR blocks
    pr = _pr(
        paths=["sandbox/foo.py"],
        changed_lines=400,
        reviews=[
            _review("owner", "APPROVED", hours_ago=73),
            _review("core1", "APPROVED", hours_ago=72),
            _review("comm1", "CHANGES_REQUESTED", hours_ago=1),
        ],
    )
    v = quorum_check.evaluate(pr, roster, [], now)
    assert not v.passed
