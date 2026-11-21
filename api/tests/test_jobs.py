from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock

import pytest
from fastapi import HTTPException

from api.app.contracts import Case, Verdict
from api.app.fake import FakeJudge
from api.app.jobs import JobRunner
from api.app.store import Store, get_case, save_case


@pytest.fixture
def store(tmp_path: Path) -> Store:
    result = Store(tmp_path)
    result.initialize()
    return result


def new_case(store: Store, case_id: str, status: str = "awaiting_video") -> None:
    case = Case.model_validate(
        dict(
            id=case_id,
            order_id="order",
            claim_type="damaged",
            description="",
            status=status,
            created_at=datetime.now(UTC),
        )
    )
    with store.transaction() as db:
        save_case(db, case)


def load(store: Store, case_id: str) -> Case:
    with store.connection() as db:
        return get_case(db, case_id)


def stage(store: Store, name: str) -> Path:
    path = store.root / name
    path.write_bytes(name.encode())
    return path


def test_concurrent_claim_and_two_worker_limit(store: Store) -> None:
    class BlockingJudge(FakeJudge):
        def __init__(self) -> None:
            self.lock = Lock()
            self.release = Event()
            self.two_started = Event()
            self.active = 0
            self.maximum = 0
            self.calls: list[str] = []

        def run(self, folder: Path) -> Verdict:
            with self.lock:
                self.calls.append(folder.name)
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                if self.active == 2:
                    self.two_started.set()
            assert self.release.wait(10)
            with self.lock:
                self.active -= 1
            return super().run(folder)

    judge = BlockingJudge()
    runner = JobRunner(store, judge)
    runner.start()
    try:
        for id in ("one", "two", "three"):
            new_case(store, id)

        def submit(name: str) -> int:
            try:
                runner.submit("one", stage(store, name))
                return 202
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as clients:
            assert sorted(clients.map(submit, ["first", "second"])) == [202, 409]
        runner.submit("two", stage(store, "another"))
        runner.submit("three", stage(store, "last"))
        assert judge.two_started.wait(10)
        case = load(store, "one")
        assert case.status == "checking"
        assert [p.event for p in case.progress] == ["started"]
        with pytest.raises(RuntimeError, match="exclusive"):
            JobRunner(store, FakeJudge()).start()
    finally:
        judge.release.set()
        runner.close()
    assert judge.maximum == 2
    assert sorted(judge.calls) == ["one", "three", "two"]
    assert load(store, "one").status == "ready"
    assert [p.event for p in load(store, "one").progress] == ["started", "finished", "done"]
    with pytest.raises(HTTPException) as exc:
        runner.submit("one", stage(store, "after-close"))
    assert exc.value.status_code == 503


@pytest.mark.parametrize("artifact", ["valid", "truncated", "wrong_case", "missing"])
def test_recovery_reuses_only_valid_saved_output(store: Store, artifact: str) -> None:
    new_case(store, "recover", "checking")
    folder = store.root / "cases/recover"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"accepted")
    saved = folder / "verdict.json"
    if artifact == "valid":
        FakeJudge().run(folder)
    elif artifact == "truncated":
        saved.write_bytes(b"{")
    elif artifact == "wrong_case":
        sample = FakeJudge().run(folder)
        sample.case_id = "other"
        saved.write_text(sample.model_dump_json())

    class CountingJudge(FakeJudge):
        calls = 0

        def run(self, folder: Path) -> Verdict:
            self.calls += 1
            return super().run(folder)

    judge = CountingJudge()
    runner = JobRunner(store, judge)
    runner.start()
    runner.close()
    case = load(store, "recover")
    assert case.status == "ready"
    assert case.verdict == Verdict.model_validate_json(saved.read_bytes())
    assert judge.calls == (0 if artifact == "valid" else 1)


def test_failed_job_retry_discards_previous_artifacts(store: Store) -> None:
    class MismatchedJudge(FakeJudge):
        def run(self, folder: Path) -> Verdict:
            verdict = super().run(folder)
            (folder / "stale-frame.jpg").write_bytes(b"old attempt")
            verdict.case_id = "other"
            return verdict

    new_case(store, "retry")
    runner = JobRunner(store, MismatchedJudge())
    runner.start()
    runner.submit("retry", stage(store, "old-upload"))
    runner.close()
    case = load(store, "retry")
    assert case.status == "failed"
    assert case.verdict is None
    assert case.progress[-1].event == "done"
    runner = JobRunner(store, FakeJudge())
    runner.start()
    runner.submit("retry", stage(store, "new-upload"))
    runner.close()
    folder = store.root / "cases/retry"
    assert (folder / "video.mp4").read_bytes() == b"new-upload"
    assert not (folder / "stale-frame.jpg").exists()
    assert load(store, "retry").status == "ready"


def test_failed_retry_restores_previous_attempt(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_case(store, "retry", "failed")
    folder = store.root / "cases/retry"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"original upload")
    runner = JobRunner(store, FakeJudge())
    runner.start()
    staged = stage(store, "replacement")
    original = Path.replace

    def fail_replace(path: Path, target: Path) -> Path:
        if path == staged:
            raise OSError("Simulated rename failure")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    try:
        with pytest.raises(OSError, match="rename failure"):
            runner.submit("retry", staged)
    finally:
        runner.close()
    assert staged.exists()
    assert load(store, "retry").status == "failed"
    assert (folder / "video.mp4").read_bytes() == b"original upload"


def test_restart_restores_uncommitted_replacement(store: Store) -> None:
    new_case(store, "retry", "failed")
    previous = store.root / ".replaced/retry"
    previous.mkdir(parents=True)
    (previous / "video.mp4").write_bytes(b"original")
    folder = store.root / "cases/retry"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"uncommitted")
    new_case(store, "unsubmitted")
    uncommitted = store.root / "cases/unsubmitted"
    uncommitted.mkdir()
    (uncommitted / "video.mp4").write_bytes(b"uncommitted")

    new_case(store, "lost", "checking")
    runner = JobRunner(store, FakeJudge())
    runner.start()
    runner.close()
    assert (folder / "video.mp4").read_bytes() == b"original"
    assert not previous.exists()
    assert not uncommitted.exists()
    assert load(store, "lost").status == "failed"


def test_crashed_intake_cleanup_requires_exclusive_ownership(store: Store) -> None:
    runner = JobRunner(store, FakeJudge())
    runner.start()
    incoming = store.root / ".incoming"
    orphan = incoming / "test.upload"
    orphan.write_bytes(b"interrupted")
    other = incoming / "readme.txt"
    other.write_bytes(b"outside upload scope")
    unrelated = stage(store, "unrelated.upload")
    try:
        with pytest.raises(RuntimeError):
            JobRunner(store, FakeJudge()).start()
        assert orphan.exists()
    finally:
        runner.close()
    runner.start()
    runner.close()
    assert not orphan.exists()
    assert unrelated.exists() and other.exists()


def test_cleanup_failure_does_not_lose_job_or_restore_stale_upload(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    class BrokenJudge:
        def run(self, case_dir: Path) -> Verdict:
            raise RuntimeError("Simulated analysis failure")

    new_case(store, "retry", "failed")
    folder = store.root / "cases/retry"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"obsolete")

    def blocked(_: Path) -> None:
        raise OSError("Simulated cleanup failure")

    runner = JobRunner(store, BrokenJudge())
    runner.start()
    with monkeypatch.context() as m:
        m.setattr(shutil, "rmtree", blocked)
        runner.submit("retry", stage(store, "latest"))
        runner.close()
    assert load(store, "retry").status == "failed"
    assert load(store, "retry").progress[-1].event == "done"
    runner.start()
    runner.close()
    assert (folder / "video.mp4").read_bytes() == b"latest"
    assert not (store.root / ".replaced/retry").exists()


def test_approval_during_pause_wakes_worker_once(store: Store) -> None:
    from api.app.contracts import ProgressEvent
    from api.app.jobs import persist_progress
    from judge import ReviewRequired

    pending = Event()
    release = Event()

    class ReviewingJudge(FakeJudge):
        calls = 0

        def run(self, folder: Path) -> Verdict:
            self.calls += 1
            persist_progress(store, folder.name, ProgressEvent(event="started", step="privacy"))
            if self.calls == 1:
                # Approval may commit before the worker returns to the runner.
                pending.set()
                assert release.wait(10)
                raise ReviewRequired("visual")
            persist_progress(store, folder.name, ProgressEvent(event="finished", step="privacy"))
            return super().run(folder)

    new_case(store, "review")
    judge = ReviewingJudge()
    runner = JobRunner(store, judge)
    runner.start()
    try:
        runner.submit("review", stage(store, "video"))
        assert pending.wait(10)
        assert load(store, "review").status == "checking"
        for _ in range(2):
            runner.resume("review")
        assert judge.calls == 1
    finally:
        release.set()
        runner.close()
    assert judge.calls == 2
    case = load(store, "review")
    assert case.status == "ready"
    assert [(event.event, event.step) for event in case.progress] == [
        ("started", "judge"),
        ("started", "privacy"),
        ("finished", "privacy"),
        ("finished", "judge"),
        ("done", None),
    ]


def test_review_pause_survives_restart(store: Store) -> None:
    from api.app.reviews import require_approval
    from judge import ReviewRequest

    class AwaitingApproval(FakeJudge):
        calls = 0

        def run(self, folder: Path) -> Verdict:
            self.calls += 1
            require_approval(store, folder.name, ReviewRequest("visual", "headers to review"))
            return super().run(folder)

    new_case(store, "review")
    judge = AwaitingApproval()
    runner = JobRunner(store, judge)
    runner.start()
    runner.submit("review", stage(store, "video"))
    runner.close()
    runner.start()
    runner.close()
    case = load(store, "review")
    assert case.status == "checking"
    assert judge.calls == 1
    assert [(entry.event, entry.step) for entry in case.progress] == [("started", "judge")]
