import threading

from PySide6.QtCore import QObject, Slot

from edi_assistant.app.worker_bridge import WorkerBridge
from edi_assistant.core.events import LogEvent, NeedsUser, RunFinished


class Receiver(QObject):
    def __init__(self):
        super().__init__()
        self.threads, self.events = [], []

    @Slot(object)
    def on_event(self, ev):
        self.threads.append(threading.current_thread())
        self.events.append(ev)


def test_sink_from_worker_thread_is_delivered_in_gui_thread(qtbot):
    bridge = WorkerBridge()
    rec = Receiver()
    bridge.log.connect(rec.on_event)
    bridge.event_received.connect(rec.on_event)
    ev = LogEvent(level="INFO", message="hi")
    with qtbot.waitSignal(bridge.log, timeout=3000):
        threading.Thread(target=bridge.sink, args=(ev,), name="worker").start()
    qtbot.waitUntil(lambda: len(rec.events) == 2, timeout=3000)
    assert all(t is threading.main_thread() for t in rec.threads)
    assert rec.events[0] is ev


def test_typed_signal_routing(qtbot):
    bridge = WorkerBridge()
    with qtbot.waitSignal(bridge.needs_user, timeout=2000) as b:
        bridge.sink(NeedsUser(request_id="r1", kind="confirm"))
    assert b.args[0].request_id == "r1"
    with qtbot.waitSignal(bridge.run_finished, timeout=2000):
        bridge.sink(RunFinished(result=None))
