from edi_assistant.automation.worker import AutomationWorker

WORKER_API = {"submit", "respond", "request_abort", "update_config", "set_advisor", "start", "stop",
              "is_running", "is_browser_open"}


def test_fake_worker_mirrors_real_worker(fake_worker):
    assert set(dir(fake_worker)) >= WORKER_API
    assert set(dir(AutomationWorker)) >= WORKER_API
