# Reflect-30 Telegram Bot

Reflect-30 是一个每 30 分钟（可配置）检查你状态的 Telegram Bot，可以记录你的回复并在每天晚上发送总结。

## 功能

1.  **定时唤醒**：每 30 分钟发送消息：“zy，过去 30 分钟你在干什么？有什么感想？”
    *   *休眠模式*：在配置的时间段（默认 23:30 - 09:30）内不会打扰。
2.  **记录**：你的回复会被自动保存到 `diary.json`，带有时间戳。
3.  **每日总结**：每天指定时间（默认 00:00）发送当天的记录汇总。
4.  **指令控制**：
    *   `/pause`：暂停定时消息。
    *   `/continue`：继续定时消息。
    *   `/stop`：停止（即暂停）。

## 安装与运行

### 1. 安装依赖

确保安装了 Python 3.8+。

```bash
pip install -r requirements.txt
```

### 2. 配置环境

创建 `.env` 文件并填入你的 Telegram Bot Token 和你的 User ID。

```bash
cp .env.example .env
```

编辑 `.env`：
```
TELEGRAM_BOT_TOKEN=你的BotToken
ALLOWED_USER_ID=你的TelegramUserID
```

> **如何获取 User ID?**
> 发送消息给 `@userinfobot` 这里的 Bot，或者使用任意 ID 获取 Bot。如果不填 ID，你必须先发送 `/start` 让 Bot 知道你是谁（但在代码中最好还是配置好 ID 以确保重启后能主动发消息）。

### 3. 修改自定义设置 (config.json)

你可以修改 `config.json` 来调整时间间隔、睡眠时间等：

```json
{
  "check_interval_minutes": 30,
  "sleep_start_time": "23:30",
  "sleep_end_time": "09:30",
  "daily_summary_time": "00:00",
  "prompt_message": "{name}，过去 {interval} 分钟你在干什么？有什么感想？",
  "admin_name": "zy"
}
```

### 4. 运行 Bot

推荐使用 `run.sh` 脚本运行，它提供了自动重启功能，能有效防止网络断连导致的程序假死。

```bash
chmod +x run.sh
./run.sh
```

或者使用原来的方式（不推荐长久运行）：

```bash
python bot.py
```
