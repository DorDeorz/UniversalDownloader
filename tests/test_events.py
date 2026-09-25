import threading

import events
from events import EventQueue, progress_from_hook


def test_events_dispatch_in_fifo_order():
    q = EventQueue()
    seen = []
    q.register(events.LOG, lambda message: seen.append(message))
    for i in range(5):
        q.post(events.LOG, message=str(i))
    assert q.dispatch_pending() == 5
    assert seen == ["0", "1", "2", "3", "4"]
    assert q.pending() == 0


def test_payload_is_passed_as_keyword_arguments():
    q = EventQueue()
    got = {}
    q.register(events.PROGRESS, lambda fraction, text: got.update(fraction=fraction, text=text))
    q.post(events.PROGRESS, fraction=0.5, text="50.0%")
    q.dispatch_pending()
    assert got == {"fraction": 0.5, "text": "50.0%"}


def test_dispatch_respects_max_events_and_keeps_the_rest():
    q = EventQueue()
    seen = []
    q.register(events.LOG, lambda message: seen.append(message))
    for i in range(10):
        q.post(events.LOG, message=i)
    assert q.dispatch_pending(max_events=3) == 3
    assert seen == [0, 1, 2]
    assert q.pending() == 7
    q.dispatch_pending()
    assert seen == list(range(10))


def test_dispatch_on_empty_queue_is_a_noop():
    assert EventQueue().dispatch_pending() == 0


def test_unregistered_kind_is_dropped():
    q = EventQueue()
    q.post("unknown", x=1)
    assert q.dispatch_pending() == 1
    assert q.pending() == 0


def test_failing_handler_is_logged_and_does_not_stop_later_events():
    q = EventQueue()
    logged = []
    q.register(events.LOG, lambda message: logged.append(message))

    def boom(**_):
        raise RuntimeError("bad widget")

    q.register(events.PROGRESS, boom)
    q.post(events.PROGRESS, fraction=0.1, text="10%")
    q.post(events.LOG, message="after")
    assert q.dispatch_pending() == 2
    assert logged == ["Internal UI error (progress): bad widget", "after"]


def test_failing_log_handler_does_not_raise():
    q = EventQueue()

    def boom(message):
        raise RuntimeError("no console")

    q.register(events.LOG, boom)
    q.post(events.LOG, message="x")
    assert q.dispatch_pending() == 1


def test_clear_drops_pending_events():
    q = EventQueue()
    seen = []
    q.register(events.LOG, lambda message: seen.append(message))
    q.post(events.LOG, message="stale")
    q.clear()
    assert q.dispatch_pending() == 0
    assert seen == []


def test_posts_from_many_threads_are_all_delivered_on_dispatching_thread():
    q = EventQueue()
    seen = []
    dispatch_threads = set()

    def handler(message):
        dispatch_threads.add(threading.get_ident())
        seen.append(message)

    q.register(events.LOG, handler)

    def worker(n):
        for i in range(200):
            q.post(events.LOG, message=(n, i))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    while q.dispatch_pending():
        pass
    assert len(seen) == 8 * 200
    assert dispatch_threads == {threading.get_ident()}
    for n in range(8):
        assert [i for (m, i) in seen if m == n] == list(range(200))


class TestProgressFromHook:
    def test_uses_byte_counters(self):
        assert progress_from_hook(
            {"status": "downloading", "downloaded_bytes": 25, "total_bytes": 100}
        ) == (0.25, "25.0%")

    def test_uses_estimate_when_total_unknown(self):
        assert progress_from_hook(
            {"status": "downloading", "downloaded_bytes": 50, "total_bytes_estimate": 200}
        ) == (0.25, "25.0%")

    def test_falls_back_to_percent_string_with_ansi_colour(self):
        fraction, text = progress_from_hook(
            {"status": "downloading", "_percent_str": "\x1b[0;94m 42.5%\x1b[0m"}
        )
        assert fraction == 0.425
        assert text == "42.5%"

    def test_clamps_out_of_range_values(self):
        assert progress_from_hook(
            {"status": "downloading", "downloaded_bytes": 150, "total_bytes": 100}
        ) == (1.0, "100.0%")

    def test_unparseable_progress_returns_none(self):
        assert progress_from_hook({"status": "downloading", "_percent_str": "N/A"}) is None
        assert progress_from_hook({"status": "downloading"}) is None

    def test_zero_total_falls_back_to_percent_string(self):
        assert progress_from_hook(
            {"status": "downloading", "downloaded_bytes": 5, "total_bytes": 0, "_percent_str": "10%"}
        ) == (0.1, "10.0%")

    def test_finished_is_full(self):
        assert progress_from_hook({"status": "finished"}) == (1.0, "100%")

    def test_other_statuses_are_ignored(self):
        assert progress_from_hook({"status": "error"}) is None
        assert progress_from_hook({}) is None
