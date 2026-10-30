"""The lab queue: never more jobs than measured, rounds fixed first, failures do not stop it."""
from __future__ import annotations

from pipeline import lab, lab_queue


class FakeProc:
    def __init__(self, log, name, code, polls=2):
        self.log, self.name, self.code, self.left, self.returncode = log, name, code, polls, None

    def poll(self):
        self.left -= 1
        if self.left > 0:
            return None
        if self.returncode is None:
            self.log.append(("end", self.name))
        self.returncode = self.code
        return self.code


def setup(monkeypatch, tmp_path, jobs=2):
    tuning = tmp_path / "tuning.toml"
    tuning.write_text(f"[lab]\nparallel_jobs = {jobs}\njob_memory_gb = 48.4\njob_cache_gb = 12.1\n")
    monkeypatch.setattr(lab_queue, "TUNING", tuning)
    monkeypatch.setattr(lab_queue, "POLL", 0)
    monkeypatch.setattr(lab, "LAB", tmp_path / "lab")
    events: list = []
    monkeypatch.setattr(lab, "load_config", lambda n: {"name": n, "reuse": None})
    monkeypatch.setattr(lab, "experiment_round", lambda cfg: events.append(("round", cfg["name"])))
    return events


def launcher(events, envs, fail=()):
    def start(cmd, stdout, stderr, env, cwd):
        name = cmd[-1]
        events.append(("start", name))
        envs.append(env)
        return FakeProc(events, name, 1 if name in fail else 0)
    return start


def test_never_more_than_the_measured_jobs(monkeypatch, tmp_path):
    events, envs = setup(monkeypatch, tmp_path, jobs=2), []
    codes = lab_queue.queue(["a", "b", "c", "d"], start=launcher(events, envs))
    assert codes == {"a": 0, "b": 0, "c": 0, "d": 0}
    live = peak = 0
    for kind, _ in events:
        live += {"start": 1, "end": -1}.get(kind, 0)
        peak = max(peak, live)
    assert peak == 2


def test_rounds_are_fixed_before_anything_starts(monkeypatch, tmp_path):
    events, envs = setup(monkeypatch, tmp_path), []
    lab_queue.queue(["a", "b", "c"], start=launcher(events, envs))
    kinds = [k for k, _ in events]
    assert kinds[:3] == ["round"] * 3 and "round" not in kinds[3:]


def test_each_job_gets_its_caps(monkeypatch, tmp_path):
    events, envs = setup(monkeypatch, tmp_path), []
    lab_queue.queue(["a"], start=launcher(events, envs))
    assert envs[0]["DEBRIS_MLX_MEMORY_GB"] == "48.4" and envs[0]["DEBRIS_MLX_CACHE_GB"] == "12.1"


def test_a_failure_does_not_stop_the_queue(monkeypatch, tmp_path):
    events, envs = setup(monkeypatch, tmp_path, jobs=1), []
    codes = lab_queue.queue(["a", "b", "c"], start=launcher(events, envs, fail={"b"}))
    assert codes == {"a": 0, "b": 1, "c": 0}


def test_phase1_expands_to_the_seven_trainings():
    assert lab_queue.expand(["phase1"]) == [f"phase1-c{n}" for n in range(2, 9)]
