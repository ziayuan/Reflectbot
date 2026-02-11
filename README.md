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

## 部署到服务器 (AWS EC2)与数据同步

为了让 Bot 24小时稳定运行，且保证数据安全（避免服务器单点故障导致数据丢失），推荐使用 **AWS EC2 运行 Bot + 本地定时同步数据** 的方案。

### 1. 服务器环境准备 (AWS EC2)

1.  在 AWS 控制台启动一个 Ubuntu 或 Amazon Linux 实例。
2.  **安全组 (Security Group)**：只需要开放 SSH (22) 端口，来源限制为你自己的 IP。
3.  SSH 连接到服务器：
    ```bash
    ssh -i "your-key.pem" ubuntu@your-server-ip
    ```
4.  安装 Python 和 Git：
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip git -y
    ```

### 2. 部署代码

在服务器上执行：

```bash
# 1. 克隆代码
git clone https://github.com/ziayuan/Reflect-30.git
cd Reflect-30

# 2. 安装依赖
pip3 install -r requirements.txt

# 3. 配置 .env
cp .env.example .env
nano .env  # 填入你的 TELEGRAM_BOT_TOKEN 和 ALLOWED_USER_ID
chmod 600 .env  # 保护隐私文件
```

### 3. 设置后台运行 (Systemd)

使用仓库中提供的 `reflect30.service` 模板来配置系统服务，这样 Bot 会开机自启且崩溃自动重启。

```bash
# 1. 修改 service 文件中的路径和用户 (如果你的用户名不是 ubuntu 或路径不同)
nano reflect30.service

# 2. 复制到系统目录
sudo cp reflect30.service /etc/systemd/system/

# 3. 启动服务
sudo systemctl daemon-reload
sudo systemctl enable reflect30
sudo systemctl start reflect30

# 查看状态
sudo systemctl status reflect30
```

### 4. 数据安全与同步 (在本地 Mac 操作)

为了保证隐私和数据安全，建议定期将服务器上的 `diary.json` 同步回本地电脑。

在你的 **本地 Mac** 上设置 `crontab` 定时任务：

1.  打开定时任务编辑器：
    ```bash
    crontab -e
    ```

2.  添加以下行（例如每小时同步一次）：
    ```bash
    # 请替换 key 路径、服务器 IP 和本地代码路径
    0 * * * * scp -i /path/to/your-key.pem ubuntu@your-server-ip:/home/ubuntu/Reflect-30/diary.json /Users/ziyuan/Code/Reflect-30/diary.json
    ```

这样，即使服务器发生故障，你的日记数据始终在本地有一份最新的备份。

