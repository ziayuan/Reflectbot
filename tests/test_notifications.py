import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Import without creating or reading a real diary/configuration.
with tempfile.TemporaryDirectory() as temp:
    previous = os.getcwd()
    os.chdir(temp)
    with patch.dict(os.environ, {"ALLOWED_USER_ID": "123", "TELEGRAM_BOT_TOKEN": ""}):
        bot = importlib.import_module('bot')
    os.chdir(previous)


class Notifications(unittest.IsolatedAsyncioTestCase):
    async def test_hourly_schedule_and_timezone(self):
        app = SimpleNamespace(bot=MagicMock(), job_queue=MagicMock())
        with tempfile.TemporaryDirectory() as temp, patch.object(bot, 'send_notification', new_callable=AsyncMock):
            previous = os.getcwd()
            try:
                os.chdir(temp)
                await bot.post_init(app)
            finally:
                os.chdir(previous)
        self.assertEqual(app.job_queue.run_repeating.call_args.kwargs['interval'], 5)
        self.assertEqual(app.job_queue.run_repeating.call_args.kwargs['first'], 1)
        self.assertEqual(app.job_queue.run_daily.call_args.kwargs['time'].utcoffset(), timedelta(hours=8))
        self.assertEqual(json.loads((ROOT / 'config.json').read_text())['check_interval_minutes'], 60)

    async def test_schedule_controls_both_channels(self):
        context = SimpleNamespace(bot=MagicMock())
        state = MagicMock()
        with patch.object(bot, 'schedule', state), patch.object(bot, 'send_notification', new_callable=AsyncMock) as send:
            state.take_due.return_value = False
            await bot.periodic_check(context)
            send.assert_not_awaited()
            state.take_due.return_value = True
            await bot.periodic_check(context)
            self.assertIn('60', send.call_args.args[2])

    async def test_reply_resets_timer_before_acknowledgement(self):
        now = datetime(2026, 10, 19, 14, 23, tzinfo=timezone(timedelta(hours=8)))
        state = MagicMock(next_due=now + timedelta(hours=1))
        update = SimpleNamespace(effective_user=SimpleNamespace(id=123), message=SimpleNamespace(text='reflection', date=now, reply_text=AsyncMock()))
        with patch.object(bot, 'schedule', state), patch.object(bot.diary, 'add_entry') as add:
            await bot.handle_message(update, None)
        add.assert_called_once_with('reflection')
        state.replied.assert_called_once_with(now)
        self.assertIn('15:23', update.message.reply_text.call_args.args[0])

    async def test_telegram_failure_still_delivers_bark(self):
        tg = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('offline')))
        with patch.object(bot, 'send_bark', new_callable=AsyncMock) as bark:
            await bot.send_notification(tg, 'title', 'body')
            bark.assert_awaited_once_with('title', 'body')

    async def test_bark_timeout_still_delivers_telegram_and_redacts_key(self):
        tg = SimpleNamespace(send_message=AsyncMock())
        client = AsyncMock()
        client.post.side_effect = bot.httpx.ConnectError('secret-device-key')
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        with patch.object(bot, 'BARK_URL', 'https://api.day.app/secret-device-key/'), patch.object(bot.httpx, 'AsyncClient', return_value=manager):
            with self.assertLogs(bot.logger, level='ERROR') as logs:
                await bot.send_notification(tg, 'title', 'body')
        tg.send_message.assert_awaited_once()
        self.assertNotIn('secret-device-key', '\n'.join(logs.output))

    async def test_bark_rest_payload_and_open_url(self):
        client = AsyncMock()
        client.post.return_value = bot.httpx.Response(200, json={'code': 200}, request=bot.httpx.Request('POST', 'https://bark.example/push'))
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        with patch.object(bot, 'BARK_URL', 'https://bark.example/key/'), patch.object(bot, 'BARK_OPEN_URL', 'https://t.me/example_bot'), patch.object(bot.httpx, 'AsyncClient', return_value=manager):
            await bot.send_bark('反思', '过去 60 分钟在想什么？')
        args = client.post.call_args
        self.assertEqual(args.args[0], 'https://bark.example/push')
        self.assertEqual(args.kwargs['json']['device_key'], 'key')
        self.assertEqual(args.kwargs['json']['url'], 'https://t.me/example_bot')

    async def test_summary_uses_previous_beijing_day_and_both_channels(self):
        now = datetime(2026, 10, 20, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(bot, 'get_now', return_value=now), patch.object(bot.diary, 'get_entries_for_day', return_value=[]) as entries, patch.object(bot, 'send_notification', new_callable=AsyncMock) as send:
            await bot.send_daily_summary(SimpleNamespace(bot=MagicMock()))
        entries.assert_called_once_with('2026-10-19')
        send.assert_awaited_once()

    async def test_other_users_cannot_pause(self):
        update = SimpleNamespace(effective_user=SimpleNamespace(id=456), message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(bot, 'schedule', MagicMock()) as state:
            await bot.pause(update, None)
            state.pause.assert_not_called()
        update.message.reply_text.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
