## 运行与开发指南
1.  **环境管理**:
    - **后端**: 本项目使用 `uv` 进行依赖管理与环境同步，请确保已安装 `uv`。

## 文档维护规范
为了确保文档始终反映系统实际状态，遵循以下原则：
- 在进行任何涉及项目结构、API 接口、核心逻辑或数据流向的变更后，必须同步检查并更新本 `AGENTS.md` 文件。
- 严禁在文档中保留过时的路径、名称或逻辑描述。

## 用户偏好

### 沟通
- 使用中文交流和回复。

### 技术栈
- **Python 包管理**: uv
- **串口隧道**: pyserial

- **组件抽象化防耦合**:
- **扩展性优先**: 组件设计时考虑后续模块扩展，抽象出通用模式（如 SidebarSection、TreeItem），而非一次性硬编码。

## 项目结构
```
tunnel/                    # 串口隧道服务
  phy/base.py             # PhysicalLayer 抽象基类
  phy/serial_phy.py       # 串口物理层实现
  phy/tcp_phy.py          # TCP 物理层实现
  frame/crc.py            # CRC16-Modbus
  frame/protocol.py       # 帧封装/解封 (0x7E成帧,无转义,CRC校验)
  tunnel.py               # Tunnel 核心: send()/recv() 帧封装透传
   proxy/                  # SOCKS5 + HTTP CONNECT 代理模块
     mux.py                # 连接复用器 (Mux)，将 Tunnel 拆分为多条逻辑连接
     server.py             # ProxyServer: 入口端 SOCKS5/HTTP CONNECT 代理
     relay.py              # RelayServer: 出口端 TCP 转发到真实目标
  bridge.py               # TCP 桥接工具（连接两个本地端口）
  __main__.py             # CLI入口，支持 tcp/udp/proxy/relay 模式
run_tunnel_a.bat           # 启动隧道 A (COM3 -> :9000)
run_tunnel_b.bat           # 启动隧道 B (COM4 -> :9001)
server.ps1                 # SOCKS5 出口服务器（gost + 隧道，有网端）
client.ps1                 # SOCKS5 客户端（gost + 隧道，无网端）
test_tunnel.py             # 端到端测试脚本
gost.exe                   # gost 隧道工具 (用于 gost 模式上层代理)
```

## 隧道架构
```
上层应用 (TCP/UDP/...)
  ↕ send() / recv()
[Tunnel]                   # 帧封装 + CRC16
  ↕ send() / recv()
[PhysicalLayer]            # 可替换: 串口 / TCP / ESP
  ↕
物理介质 (COM3 / COM4 / 网络)
```

- **PhysicalLayer**: 抽象物理层接口，`send()` / `recv()`，可替换实现
- **FrameProto**: `[0x7E][len:2BE][payload:var][crc16:2LE][0x7E]`，无字节填充，Length+CRC 双重校验，错误帧丢弃
- **Tunnel**: 纯 `send(data)` / `recv(timeout)`，不关心上层传输协议
- **Mux** (`tunnel/proxy/mux.py`): 在 Tunnel 之上实现连接复用，用 [conn_id:1B][type:1B][payload] 子帧格式区分多路连接，支持 OPEN/DATA/CLOSE 帧类型
- **ProxyServer** (`tunnel/proxy/server.py`): 入口端 SOCKS5 + HTTP CONNECT 代理，自动探测协议，通过 Mux 将请求发往出口端
- **RelayServer** (`tunnel/proxy/relay.py`): 出口端 TCP 转发器，收到 OPEN 帧后连接到真实目标并桥接数据
- **bridge.py**: TCP 桥接工具，用于 gost 模式下连接隧道出口与本地 gost 服务

### 两种代理方案

| 方案 | 启动方式 | SOCKS5 实现 | 适用场景 |
|------|---------|-------------|---------|
| **gost 模式（默认）** | `server.ps1` + `client.ps1` | gost 处理协议 | 有 gost 环境，可靠性优先 |
| **内置模式（零依赖）** | `--mode proxy/relay` | 纯 Python 自实现 | 无 gost，需要最小依赖 |

### 开发原则
- **单一事实来源 (Single Source of Truth)**
- **最小改动原则**
- **显式优于隐式**