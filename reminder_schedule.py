"""Persistent reminder timing, independent of notification transports."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path


class ReminderSchedule:
    def __init__(self, path, now, interval_minutes=60, attempts=5, retry_seconds=60):
        self.path = Path(path)
        self.interval = timedelta(minutes=interval_minutes)
        self.attempts = attempts
        self.retry = timedelta(seconds=retry_seconds)
        if interval_minutes <= 0 or attempts < 1 or retry_seconds <= 0:
            raise ValueError('Reminder timing values must be positive')
        self.next_due = now + self.interval
        self.sent = 0
        self.paused = False
        self.last_reply = None
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self.next_due = datetime.fromisoformat(data['next_due'])
            self.sent = int(data['sent'])
            self.paused = bool(data['paused'])
            self.last_reply = datetime.fromisoformat(data['last_reply']) if data.get('last_reply') else None
            if self.next_due.tzinfo is None or not 0 <= self.sent < attempts:
                raise ValueError('Invalid reminder state')
        else:
            self.save()

    def save(self):
        temporary = self.path.with_suffix(self.path.suffix + '.tmp')
        temporary.write_text(json.dumps({
            'next_due': self.next_due.isoformat(),
            'sent': self.sent,
            'paused': self.paused,
            'last_reply': self.last_reply.isoformat() if self.last_reply else None,
        }) + '\n')
        os.replace(temporary, self.path)

    def replied(self, when):
        # Delayed Telegram updates must never move a newer reply backwards.
        if self.last_reply is not None and when <= self.last_reply:
            return
        self.last_reply = when
        self.next_due = when + self.interval
        self.sent = 0
        self.save()

    def pause(self):
        self.paused = True
        self.save()

    def resume(self, now):
        self.paused = False
        self.next_due = now + self.interval
        self.sent = 0
        self.save()

    def take_due(self, now, sleeping=False):
        if self.paused or now < self.next_due:
            return False
        if sleeping:
            # An interrupted burst starts fresh when quiet hours end.
            if self.sent:
                self.sent = 0
                self.save()
            return False
        self.sent += 1
        if self.sent >= self.attempts:
            self.sent = 0
            self.next_due = now + self.interval
        else:
            self.next_due = now + self.retry
        # Advance before awaiting network calls so a concurrent reply wins.
        # After downtime send once, never replay missed reminders in a burst.
        self.save()
        return True
