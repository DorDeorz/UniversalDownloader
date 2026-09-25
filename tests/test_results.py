from results import ItemResult, ItemStatus, JobSummary, verify_output


def r(status, title="t", error=None, path=None):
    return ItemResult(f"https://x/{title}", title, status, path=path, error=error)


def test_headline_counts_each_status():
    s = JobSummary([r(ItemStatus.COMPLETED), r(ItemStatus.COMPLETED), r(ItemStatus.FAILED), r(ItemStatus.SKIPPED)])
    assert s.headline() == "2 completed, 1 failed, 1 skipped"
    assert not s.all_ok


def test_all_completed_is_ok():
    s = JobSummary([r(ItemStatus.COMPLETED)])
    assert s.all_ok
    assert s.title() == "Download complete"


def test_empty_job_is_not_ok():
    s = JobSummary()
    assert not s.all_ok
    assert s.headline() == "Nothing to download"


def test_titles_reflect_outcome():
    assert JobSummary([r(ItemStatus.FAILED)]).title() == "Download failed"
    assert JobSummary([r(ItemStatus.COMPLETED), r(ItemStatus.FAILED)]).title() == "Download partly failed"
    assert JobSummary([r(ItemStatus.COMPLETED), r(ItemStatus.CANCELLED)]).title() == "Download cancelled"


def test_report_lists_problem_items_only():
    s = JobSummary([r(ItemStatus.COMPLETED, "good"), r(ItemStatus.FAILED, "bad", "HTTP 403")])
    assert s.report() == "1 completed, 1 failed\n- failed: bad: HTTP 403"


def test_report_truncates_long_lists():
    s = JobSummary([r(ItemStatus.FAILED, f"v{i}") for i in range(12)])
    lines = s.report(limit=10).splitlines()
    assert len(lines) == 12
    assert lines[-1] == "... and 2 more"


def test_describe():
    assert r(ItemStatus.COMPLETED, path="/a.mp4").describe() == "Saved: /a.mp4"
    assert r(ItemStatus.FAILED, "x", "boom").describe() == "Failed: x (boom)"
    assert r(ItemStatus.CANCELLED, "x").describe() == "Cancelled: x"


def test_verify_output(tmp_path):
    good = tmp_path / "a.mp4"
    good.write_bytes(b"x")
    empty = tmp_path / "b.mp4"
    empty.write_bytes(b"")
    assert verify_output(str(good)) is None
    assert "empty" in verify_output(str(empty))
    assert "not created" in verify_output(str(tmp_path / "missing.mp4"))
    assert verify_output(None)
