# Reflectbot：每小时反思提醒

初始在启动后 60 分钟同时通过 Telegram 和 Bark 提醒；每次回复后，按回复时间往后推 60 分钟。到时未回复，每隔 1 分钟提醒一次，总共 5 次；仍未回复，从第 5 次起再等 60 分钟开始下一轮。回复请发给 Telegram Bot，记录保存在 `diary.json`。Bark 通知可点击打开 Telegram Bot。两个渠道独立发送，一个失败不会阻止另一个。

北京时间 23:30–09:30 免打扰，00:00 汇总前一天的记录并发送到两个渠道。`/pause`、`/continue`、`/stop` 同时控制两个渠道的定时提醒。

## dj 部署

安装位置 `/opt/Reflectbot`，服务名 `reflect30`，使用专用用户 `reflectbot`。创建 Python 3.11+ 虚拟环境 `venv`，安装 `requirements.txt`，将 `.env.example` 复制为 `.env` 并填写：

- `TELEGRAM_BOT_TOKEN`：此机器人的 Token。
- `ALLOWED_USER_ID`：你的 Telegram 数字 User ID（部署时必填）。
- `BARK_URL`：Bark App 中的完整地址 `https://api.day.app/设备Key/`，也支持自建 HTTPS 服务。
- `BARK_OPEN_URL`：可选，`https://t.me/机器人用户名`。

首次使用须在 Telegram 中向机器人发送 `/start`。不要同时在多台机器轮询同一个 Bot。`.env` 和 `diary.json` 不提交到 Git。

```bash
chown -R reflectbot:reflectbot /opt/Reflectbot
chmod 600 /opt/Reflectbot/.env
cp reflect30.service /etc/systemd/system/reflect30.service
systemctl daemon-reload
systemctl enable --now reflect30
systemctl status reflect30
journalctl -u reflect30 -n 50
```

初始不是固定整点；例如 14:23 回复，下次在 15:23 提醒，未回复则在 15:24、15:25、15:26、15:27 继续提醒，再下一轮从 16:27 开始。调度每 5 秒检查一次。

计时、当前轮次和暂停状态保存在 `reminder_state.json`，重启后恢复，不补发停机期间错过的多次提醒。免打扰期间到期的提醒顺延到免打扰结束，开启新一轮。`/continue` 后等待 60 分钟再提醒。每日汇总不受 `/pause` 影响。请勿将 `.env`、日记和计时状态文件提交到 Git。

Bark 使用 [官方 REST API](https://github.com/Finb/bark-server/blob/master/docs/API_V2.md)。

## 本地运行

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 后运行
venv/bin/python bot.py
```

`config.json` 可调整提醒间隔、免打扰时间、每日总结时间和提醒文案。所有时间均按北京时间处理。

## Telegram 指令

- `/start`：查看当前设置。
- `/pause`、`/stop`：暂停定时提醒。
- `/continue`、`/resume`：恢复定时提醒。
- `/summary`：查看今天的记录。
- `/summary YYYYMMDD`：查看指定日期的记录。

直接发送文字即可保存记录。每天的自动总结在两个渠道发送，手动 `/summary` 在 Telegram 中回复。

## 验证

```bash
venv/bin/python -m unittest discover -s tests -v
```
