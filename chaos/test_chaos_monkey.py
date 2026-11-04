"""Offline tests for chaos_monkey.py safety rails, using a fake EC2 client (no AWS calls)."""
import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import chaos_monkey  # noqa: E402


class FakeEC2:
    def __init__(self, instances):
        self.instances = instances  # list of (id, az, tags)
        self.terminated, self.stopped = [], []

    def get_paginator(self, _):
        fake = self

        class P:
            def paginate(self, Filters):
                want = {f["Name"]: f["Values"] for f in Filters}
                out = []
                for iid, az, tags in fake.instances:
                    if any(tags.get(k[4:]) not in v for k, v in want.items() if k.startswith("tag:")):
                        continue
                    if "availability-zone" in want and az not in want["availability-zone"]:
                        continue
                    if iid in fake.terminated:
                        continue
                    out.append({"InstanceId": iid, "Placement": {"AvailabilityZone": az}})
                return [{"Reservations": [{"Instances": out}]}]
        return P()

    def terminate_instances(self, InstanceIds):
        self.terminated += InstanceIds

    def stop_instances(self, InstanceIds):
        self.stopped += InstanceIds


S2 = {"project": "mini-netflix", "stage": "s2"}


def run(monkeypatch, tmp_path, fake, *argv):
    monkeypatch.setattr(chaos_monkey.boto3, "client", lambda *a, **k: fake)
    monkeypatch.setattr(chaos_monkey.time, "sleep", lambda s: None)
    events = tmp_path / "events.csv"
    monkeypatch.setattr(sys, "argv", ["chaos_monkey.py", "--events", str(events), "--initial-delay", "0", *argv])
    chaos_monkey.main()
    return list(csv.DictReader(open(events))) if events.exists() else []


def test_only_tagged_instances_are_candidates(monkeypatch, tmp_path):
    fake = FakeEC2([("i-a", "us-east-1a", S2), ("i-other", "us-east-1a", {"project": "someone-else", "stage": "s2"}),
                    ("i-s1", "us-east-1a", {"project": "mini-netflix", "stage": "s1"})])
    rows = run(monkeypatch, tmp_path, fake, "--stage", "s2", "--once")
    assert fake.terminated == ["i-a"] and rows[0]["target"] == "i-a"


def test_refuses_when_filter_matches_too_many(monkeypatch, tmp_path):
    fake = FakeEC2([(f"i-{n}", "us-east-1a", S2) for n in range(5)])
    with pytest.raises(SystemExit):
        run(monkeypatch, tmp_path, fake, "--stage", "s2", "--once", "--max-instances", "4")
    assert fake.terminated == []


def test_dry_run_touches_nothing(monkeypatch, tmp_path):
    fake = FakeEC2([("i-a", "us-east-1a", S2)])
    rows = run(monkeypatch, tmp_path, fake, "--stage", "s2", "--once", "--dry-run")
    assert fake.terminated == [] and rows[0]["dry_run"] == "True"


def test_az_mode_kills_every_instance_in_that_az_only(monkeypatch, tmp_path):
    fake = FakeEC2([("i-a1", "us-east-1a", S2), ("i-a2", "us-east-1a", S2), ("i-b1", "us-east-1b", S2)])
    rows = run(monkeypatch, tmp_path, fake, "--stage", "s2", "--az", "us-east-1a")
    assert sorted(fake.terminated) == ["i-a1", "i-a2"] and all(r["action"] == "az-terminate" for r in rows)


def test_stop_action_for_s1(monkeypatch, tmp_path):
    fake = FakeEC2([("i-s1", "us-east-1a", {"project": "mini-netflix", "stage": "s1"})])
    run(monkeypatch, tmp_path, fake, "--stage", "s1", "--action", "stop", "--once")
    assert fake.stopped == ["i-s1"] and fake.terminated == []
