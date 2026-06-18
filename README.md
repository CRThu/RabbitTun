<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blue" alt="version">
  <img src="https://img.shields.io/badge/python-3.14+-green" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="license">
</p>

<h1 align="center">RabbitTun</h1>

<p align="center">
  串口 TCP 隧道 — 支持串口、ESP、BLE 等任意物理层
</p>

<p align="center">
  无需以太网 / WiFi / 路由器，一根串口线打通两台机器。
</p>

---

## Features

- TCP 字节流透传，支持任意协议（SSH、HTTP、SOCKS 等）
- 多路复用 — 多个 TCP 连接并发共享同一串口链路
- PHY 层可插拔 — 串口、ESP、TCP、BLE 均可，实现 `Phy` 接口即可
- 帧同步 + CRC16-MODBUS 校验，数据可靠
- 自动重连，断线恢复
- 单文件 exe，开箱即用

## 快速开始

### 构建

```bash
uv run python -m nuitka --standalone --output-filename=rabbit-tun.exe run.py
```

### 用法

```
rabbit-tun <phy> [选项]

phy         COM3, COM3:9600, tcp:host:port
-l PORT     监听 TCP，桥接到 PHY
-t TARGET   连接 PHY 到 TCP 目标 (host:port)
```

## 场景

### 1. 远程 SSH 到内网机器

内网机器有 SSH 服务，外网机器想 SSH 进去。

```
  External Machine              Serial Link             Internal Machine
  +----------------+          +--------------+          +----------------+
  |                |  SSH     |   :2222      |   PHY    |   :22          |
  |  ssh -p 2222   | -------->|  rabbit-tun  | ========>|  sshd          |
  |                | <--------|              | <========|                |
  +----------------+          +--------------+          +----------------+
       COM3                      serial                    COM18
```

**内网机器 (COM18):**

```bash
.\rabbit-tun.exe COM18 -t 127.0.0.1:22
```

**外网机器 (COM3):**

```bash
.\rabbit-tun.exe COM3 -l 2222
```

**连接:**

```bash
ssh -p 2222 user@127.0.0.1
```

---

### 2. 内网通过外网代理上网

内网机器无外网，外网机器有代理（如 Clash :7890）。

```
  Internal Machine            Serial Link           External Machine      Internet
  +----------------+        +--------------+        +--------------+      +-------+
  |                | curl   |   :9000      |   PHY  |   :7890      |      |       |
  |  curl -x       | ------>|  rabbit-tun  | ======>|  proxy       | ---->|  web  |
  |  http://...    | <------|              | <======|  (Clash)     | <----|       |
  +----------------+        +--------------+        +--------------+      +-------+
       COM18                   serial                  COM3
```

**外网机器 (COM3):**

```bash
.\rabbit-tun.exe COM3 -t 127.0.0.1:7890
```

**内网机器 (COM18):**

```bash
.\rabbit-tun.exe COM18 -l 9000
```

**内网上网:**

```bash
# 单次请求
curl -x http://127.0.0.1:9000 https://example.com

# 全局代理 (Linux/macOS)
export http_proxy=http://127.0.0.1:9000
export https_proxy=http://127.0.0.1:9000
curl https://example.com

# 全局代理 (Windows PowerShell)
$env:http_proxy="http://127.0.0.1:9000"
$env:https_proxy="http://127.0.0.1:9000"
```

## 协议

TCP 字节流透传，不解析上层协议。多路复用模式下帧头包含 TYPE 和 SESSION ID。

```
+--------+--------+------+--------+-------------+--------+--------+
|  HEAD  |  LEN   | TYPE |  SID   |    DATA     |  CRC   |  TAIL  |
| 1 B    | 2 B    | 1 B  | 1 B    |  max 4 KB   | 2 B    | 1 B    |
+--------+--------+------+--------+-------------+--------+--------+
  0x7E     n       CMD    SID      payload      CRC16    0x7F

TYPE: DATA=0x00, OPEN=0x01, CLOSE=0x02
```

## PHY 层

PHY 层可插拔。内置实现：

| PHY | 示例 |
|-----|------|
| Serial | `COM3`, `COM3:9600` |
| TCP | `tcp:host:port` |
| ESP | 继承 `Phy` 类，用 ESP-NOW / UART 桥接 |
| BLE | 继承 `Phy` 类，用 BLE 串口透传 |

添加新 PHY：继承 `Phy` 类，实现 `open`、`close`、`send`、`recv` 即可。

## 依赖

- Python 3.14+
- pyserial

## License

MIT
