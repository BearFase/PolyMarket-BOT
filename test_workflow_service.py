"""The hourly task runs the workflow under pythonw.exe, which has no console.

workflow_service must rebind stdout and stderr to its log before the workflow
runs, pass the arguments through, and return the workflow's exit code so Task
Scheduler still records failures.
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import workflow_service


class WorkflowServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log_path = Path(tmp.name) / "logs" / "workflow_console.log"
        self.saved = (sys.stdout, sys.stderr, os.getcwd())
        self.addCleanup(self.restore)

    def restore(self):
        log = sys.stdout
        sys.stdout, sys.stderr = self.saved[0], self.saved[1]
        os.chdir(self.saved[2])
        if log is not self.saved[0] and hasattr(log, "close"):
            log.close()

    def test_output_goes_to_the_log_and_the_exit_code_is_returned(self):
        seen = {}
        workflow = types.ModuleType("nfl_daily_update")

        def fake_main(argv):
            seen["argv"] = argv
            seen["stdout"] = getattr(sys.stdout, "name", None)
            seen["stderr_is_stdout"] = sys.stderr is sys.stdout
            print("run summary")
            return 1

        workflow.main = fake_main
        with mock.patch.object(workflow_service, "CONSOLE_LOG", self.log_path), \
                mock.patch.dict(sys.modules, {"nfl_daily_update": workflow}):
            code = workflow_service.main(["--dry-run"])
        self.restore()

        self.assertEqual(1, code)
        self.assertEqual(["--dry-run"], seen["argv"])
        self.assertEqual(str(self.log_path), seen["stdout"])
        self.assertTrue(seen["stderr_is_stdout"])
        self.assertIn("run summary", self.log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
