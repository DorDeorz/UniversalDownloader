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


def test_skipped_items_are_not_failures():
    # Private or deleted playlist entries are skipped, not failed.
    assert JobSummary([r(ItemStatus.SKIPPED), r(ItemStatus.SKIPPED)]).title() == "Nothing downloaded"
    s = JobSummary([r(ItemStatus.COMPLETED), r(ItemStatus.SKIPPED)])
    assert s.no_problems and not s.all_ok
    assert s.title() == "Download complete"
    assert JobSummary([r(ItemStatus.SKIPPED), r(ItemStatus.FAILED)]).title() == "Download failed"


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


class _Probe:
    """Stands in for subprocess.run with ffprobe's answer."""

    def __init__(self, streams=None, returncode=0, error=None):
        self.streams, self.returncode, self.error = streams, returncode, error
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if self.error:
            raise self.error
        import json
        import subprocess
        out = json.dumps({"streams": self.streams}) if self.streams is not None else ""
        return subprocess.CompletedProcess(command, self.returncode, out, "Invalid data found")


def test_probe_accepts_a_file_with_the_tracks_asked_for():
    from results import probe_output
    run = _Probe([{"codec_type": "video"}, {"codec_type": "audio"}])
    assert probe_output("a.mp4", "ffprobe", need_video=True, run=run) is None
    assert run.commands[0][0] == "ffprobe" and run.commands[0][-1] == "a.mp4"


def test_probe_finds_a_damaged_file():
    from results import DAMAGED, probe_output
    assert probe_output("a.mp4", "ffprobe", run=_Probe(None, returncode=1)) == DAMAGED
    assert probe_output("a.mp4", "ffprobe", run=_Probe([])) == DAMAGED


def test_probe_finds_a_missing_track_and_ignores_cover_images():
    from results import NO_AUDIO_TRACK, NO_VIDEO_TRACK, probe_output
    cover_only = [{"codec_type": "video", "disposition": {"attached_pic": 1}}, {"codec_type": "audio"}]
    assert probe_output("a.mp3", "ffprobe", need_audio=True, run=_Probe(cover_only)) is None
    assert probe_output("a.mp4", "ffprobe", need_video=True, run=_Probe(cover_only)) == NO_VIDEO_TRACK
    assert probe_output("a.m4a", "ffprobe", need_audio=True, run=_Probe([{"codec_type": "video"}])) == NO_AUDIO_TRACK


def test_probe_is_skipped_without_ffprobe_or_when_it_fails():
    import subprocess
    from results import probe_output
    assert probe_output("a.mp4", None, need_video=True, run=_Probe([])) is None
    assert probe_output("a.mp4", "ffprobe", run=_Probe(error=subprocess.TimeoutExpired("ffprobe", 60))) is None
    assert probe_output("a.mp4", "ffprobe", run=_Probe(error=OSError("gone"))) is None
