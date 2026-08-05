from __future__ import annotations

import sys
import time

from catalyst_literature.processes import ChildProcessJob


def test_closing_job_kills_child_process() -> None:
    job = ChildProcessJob()
    child = job.start([sys.executable, "-c", "import time; time.sleep(60)"])
    assert child.process.poll() is None
    job.close()
    deadline = time.monotonic() + 5
    while child.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert child.process.poll() is not None
