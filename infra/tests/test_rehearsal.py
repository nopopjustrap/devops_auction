"""Regression checks for early QEMU failure and guest readiness."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from rehearsal import wait_for_boot


class GuestStartupTests(unittest.TestCase):
    def test_exited_guest_fails_before_ssh_is_attempted(self):
        process = SimpleNamespace(poll=lambda: 1)
        probe = Mock()
        pause = Mock()
        with self.assertRaisesRegex(
            RuntimeError, "staging: QEMU exited.*staging-console.log"
        ):
            wait_for_boot("staging", process, probe, pause=pause)
        probe.assert_not_called()
        pause.assert_not_called()

    def test_running_guest_can_finish_booting_after_a_retry(self):
        process = SimpleNamespace(poll=lambda: None)
        probe = Mock(
            side_effect=[
                SimpleNamespace(returncode=1),
                SimpleNamespace(returncode=0),
            ]
        )
        pause = Mock()
        wait_for_boot("test", process, probe, attempts=2, pause=pause)
        self.assertEqual(probe.call_count, 2)
        pause.assert_called_once_with(2)

    def test_running_but_unready_guest_has_a_bounded_wait(self):
        process = SimpleNamespace(poll=lambda: None)
        probe = Mock(return_value=SimpleNamespace(returncode=1))
        pause = Mock()
        with self.assertRaisesRegex(RuntimeError, "Debian did not become ready"):
            wait_for_boot("test", process, probe, attempts=3, pause=pause)
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(pause.call_count, 3)


if __name__ == "__main__":
    unittest.main()
