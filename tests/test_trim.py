import math
from unittest import mock

import pytest
import yt_dlp

import logic
from logic import DownloadManager, TrimError, parse_timestamp, parse_trim_range
from results import ItemStatus

from conftest import FAKE_TOOLS


@pytest.mark.parametrize("text, expected", [
    ("10", 10.0),
    ("10.5", 10.5),
    ("0", 0.0),
    ("1:30", 90.0),
    ("01:30", 90.0),
    ("1:02:03", 3723.0),
    ("00:00:10", 10.0),
    ("1:02:03.25", 3723.25),
    ("  15  ", 15.0),
    ("90", 90.0),
    ("75:00", 4500.0),
])
def test_parse_timestamp_valid(text, expected):
    assert parse_timestamp(text) == expected


@pytest.mark.parametrize("text", [None, "", "   "])
def test_parse_timestamp_empty_is_none(text):
    assert parse_timestamp(text) is None


@pytest.mark.parametrize("text", [
    "-5", "abc", "1:2:3:4", "1:60", "1:75:00", "1.5:30", ":30", "30:", "1e3", "*10-20", "10-20",
])
def test_parse_timestamp_invalid(text):
    with pytest.raises(TrimError):
        parse_timestamp(text)


def test_range_both_empty_means_no_trim():
    assert parse_trim_range("", None) is None


def test_range_start_only_runs_to_end_of_video():
    assert parse_trim_range("10", "", duration=60) == (10.0, 60.0)
    assert parse_trim_range("10", "") == (10.0, math.inf)


def test_range_end_only_starts_at_zero():
    assert parse_trim_range("", "0:20") == (0.0, 20.0)


@pytest.mark.parametrize("start, end", [("20", "10"), ("10", "10"), ("0", "0")])
def test_range_start_must_be_before_end(start, end):
    with pytest.raises(TrimError, match="before end"):
        parse_trim_range(start, end)


def test_range_must_fit_duration():
    assert parse_trim_range("10", "60", duration=60) == (10.0, 60.0)
    with pytest.raises(TrimError, match="beyond the video length"):
        parse_trim_range("10", "61", duration=60)
    with pytest.raises(TrimError, match="beyond the video length"):
        parse_trim_range("60", "", duration=60)


def test_range_works_with_yt_dlp_download_range_func():
    # Regresyon: eski kod '*10-20' string'i veriyordu ve burada ValueError atıyordu
    ranges = yt_dlp.utils.download_range_func(None, [parse_trim_range("10", "20")])
    assert list(ranges({"id": "x", "duration": 60}, None)) == [{"start_time": 10.0, "end_time": 20.0}]


def _run_download(options, info, tmp_path):
    """download_video'yu sahte YoutubeDL ile çalıştırır; (ydl_cls, ydl, result) döner."""
    options = dict(options, save_path=str(tmp_path))
    ydl = mock.MagicMock()
    ydl.params = {}
    ydl.prepare_filename.return_value = str(tmp_path / "Other" / "t.mp4")
    ydl.extract_info.return_value = info
    ydl.process_ie_result.return_value = dict(info, requested_downloads=[{"filepath": "out.mp4"}])
    ydl_cls = mock.MagicMock()
    ydl_cls.return_value.__enter__.return_value = ydl
    with mock.patch.object(logic.yt_dlp, "YoutubeDL", ydl_cls), \
            mock.patch.object(logic, "verify_output", return_value=None):
        result = DownloadManager(tools=FAKE_TOOLS).download_video("https://youtu.be/x", options, lambda d: None)
    return ydl_cls, ydl, result


def test_download_with_trim_passes_start_end_pair(tmp_path):
    info = {"id": "x", "title": "t", "duration": 60}
    ydl_cls, ydl, result = _run_download({"trim_start": "0:10", "trim_end": "20"}, info, tmp_path)

    assert result.status is ItemStatus.COMPLETED
    assert result.path == "out.mp4"
    ydl.extract_info.assert_called_once_with("https://youtu.be/x", download=False)
    ydl.process_ie_result.assert_called_once_with(info, download=True)
    probe_opts, download_opts = ydl_cls.call_args_list[0].args[0], ydl_cls.call_args_list[-1].args[0]
    assert "download_ranges" not in probe_opts
    assert download_opts["force_keyframes_at_cuts"] is True
    ranges = download_opts["download_ranges"]
    assert list(ranges(info, ydl)) == [{"start_time": 10.0, "end_time": 20.0}]


def test_download_with_invalid_trim_text_never_starts(tmp_path):
    ydl_cls, ydl, result = _run_download({"trim_start": "20", "trim_end": "10"}, {}, tmp_path)

    ydl_cls.assert_not_called()
    assert result.status is ItemStatus.FAILED
    assert "before end" in result.error


def test_download_with_trim_past_duration_reports_error(tmp_path):
    info = {"id": "x", "title": "t", "duration": 15}
    _, ydl, result = _run_download({"trim_start": "10", "trim_end": "20"}, info, tmp_path)

    ydl.process_ie_result.assert_not_called()
    assert result.status is ItemStatus.FAILED
    assert "beyond the video length" in result.error


def test_download_without_trim_is_unchanged(tmp_path):
    info = {"id": "x", "title": "t", "duration": 60}
    ydl_cls, ydl, result = _run_download({"trim_start": None, "trim_end": None}, info, tmp_path)

    assert "download_ranges" not in ydl_cls.call_args.args[0]
    assert "download_ranges" not in ydl.params
    assert "force_keyframes_at_cuts" not in ydl_cls.call_args.args[0]
    assert result.status is ItemStatus.COMPLETED


def test_download_with_blank_trim_fields_does_not_trim(tmp_path):
    info = {"id": "x", "title": "t", "duration": 60}
    ydl_cls, ydl, result = _run_download({"trim_start": "  ", "trim_end": ""}, info, tmp_path)

    assert result.status is ItemStatus.COMPLETED
    assert "download_ranges" not in ydl.params
