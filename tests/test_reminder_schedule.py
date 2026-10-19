import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from reminder_schedule import ReminderSchedule


class Timing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.json'
        self.now = datetime(2026, 10, 19, 14, 23, tzinfo=timezone(timedelta(hours=8)))
        self.state = ReminderSchedule(self.path, self.now)

    def test_first_reminder_then_five_attempts_then_hour(self):
        self.assertFalse(self.state.take_due(self.now + timedelta(minutes=59)))
        first = self.now + timedelta(hours=1)
        for index in range(5):
            when = first + timedelta(minutes=index)
            self.assertTrue(self.state.take_due(when))
            self.assertFalse(self.state.take_due(when + timedelta(seconds=59)))
        self.assertEqual(self.state.next_due, first + timedelta(minutes=64))
        self.assertTrue(self.state.take_due(first + timedelta(minutes=64)))

    def test_reply_cancels_burst_and_moves_deadline(self):
        self.state.take_due(self.now + timedelta(hours=1))
        reply = self.now + timedelta(hours=1, seconds=30)
        self.state.replied(reply)
        self.assertFalse(self.state.take_due(self.now + timedelta(minutes=61)))
        self.assertEqual(self.state.sent, 0)
        self.assertTrue(self.state.take_due(reply + timedelta(hours=1)))

    def test_each_reply_extends_timer_and_old_updates_do_not_rewind(self):
        self.state.replied(self.now)
        self.state.replied(self.now + timedelta(minutes=10))
        self.state.replied(self.now - timedelta(minutes=1))
        self.assertEqual(self.state.next_due, self.now + timedelta(minutes=70))

    def test_restart_preserves_reply_and_burst(self):
        self.state.replied(self.now)
        self.state.take_due(self.now + timedelta(hours=1))
        restored = ReminderSchedule(self.path, self.now + timedelta(minutes=61))
        self.assertEqual(restored.next_due, self.now + timedelta(minutes=61))
        self.assertEqual(restored.sent, 1)
        self.assertEqual(restored.last_reply, self.now)

    def test_pause_persists_and_resume_waits_one_hour(self):
        self.state.pause()
        restored = ReminderSchedule(self.path, self.now)
        self.assertFalse(restored.take_due(self.now + timedelta(days=1)))
        restored.resume(self.now + timedelta(days=1))
        self.assertEqual(restored.next_due, self.now + timedelta(days=1, hours=1))

    def test_quiet_hours_stop_burst_and_morning_starts_fresh(self):
        self.state.take_due(self.now + timedelta(hours=1))
        self.assertFalse(self.state.take_due(self.now + timedelta(minutes=61), sleeping=True))
        self.assertEqual(self.state.sent, 0)
        morning = self.now + timedelta(days=1)
        self.assertTrue(self.state.take_due(morning, sleeping=False))
        self.assertEqual(self.state.next_due, morning + timedelta(minutes=1))
        self.assertEqual(self.state.sent, 1)

    def test_downtime_sends_once_without_replaying_missed_reminders(self):
        late = self.now + timedelta(days=1)
        self.assertTrue(self.state.take_due(late))
        self.assertFalse(self.state.take_due(late))
        self.assertEqual(self.state.next_due, late + timedelta(minutes=1))
