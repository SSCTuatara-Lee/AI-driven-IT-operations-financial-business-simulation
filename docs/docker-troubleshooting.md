# Docker / WSL 重启后诊断

本机诊断日期：2026-09-28。诊断命令只读，不修改系统服务、注册表或发行版：

    .venv\Scripts\python.exe scripts\diagnose_docker.py

## 当前处理结果：Hyper-V 已运行

用户选择保留当前 Windows、使用 Docker 官方 Hyper-V 后端。已设置 WslEngineEnabled=false，并启动 com.docker.service（自动启动）。Windows Update 配置未改动，未安装 Windows 累积更新。Containers 可选功能仍为 Disabled，本次 Linux 容器实际运行和业务验收均通过。

Docker Engine 29.8.0 / LinuxKit 7.0.12、MySQL 8.0.46、应用容器均已运行。入口 http://127.0.0.1:8001/，日常使用 start-docker.cmd 启动，不再依赖 WSL 更新。启动脚本会等待容器健康检查通过。

Docker 虚拟机的活动数据磁盘为 D:/lxt/.tools/docker-data/hyper-v/DockerDesktop.vhdx。原 C 盘磁盘保留作备份。Docker 对磁盘使用受保护权限，普通复制及 Hyper-V 存储迁移被拒绝；最终在虚拟机关机时通过 Windows 管理员备份权限复制，没有放宽源文件 ACL。复制后已验证原压测报告、交易记录和账务一致性仍在，记录见 data/docker-persistence-verification.json。

切换前的 Docker 设置备份在 data/backups/docker-settings-before-hyperv.json。磁盘复制脚本属于本次维护工具，有备份存在检查，日常启动不需要再次执行。

## 原 WSL 启动阻塞（仍未修复，不影响当前 Hyper-V 运行）

- Windows 10 Pro 22H2，系统内部版本为 **19045.2006**，累计更新记录停在 2022 年 9 月。
- 新版 WSL **2.7.14.0** 已安装在 C:/Program Files/WSL。
- 直接调用新版 wsl.exe --status 返回 **Wsl/WSL_E_OS_NOT_SUPPORTED**，明确表示当前 Windows 不支持打包版本的 WSL。
- PATH 中优先命中 C:/Windows/System32/wsl.exe，它仍是旧版，连 --version 都不支持。
- Windows Update 服务 wuauserv 为 **DISABLED**。尚未改变该设置；不能只靠重试更新解决。
- HypervisorPresent 为 true，vmcompute 已运行，Hyper-V PowerShell 模块存在。重启后虚拟化组件已运行，因此不能仅凭旧 CPU 特性探测函数返回 false 就断定 BIOS 没开虚拟化。
- Docker CLI 可用，context 为 desktop-linux；Docker 引擎返回 Docker Desktop is unable to start。
- 用户执行 wsl --update 遇到 403 / 0x80190193，说明该次更新请求被拒绝；目前未确定是哪个网络环节返回的 403。

## 将来需要切回 WSL2 时的处理顺序

1. 补齐 Windows 累积更新，再验证 WSL。微软说明，Windows 10 的新版 WSL 支持由 KB5020030 引入（19045.2311）；后续累计更新也包含这些系统组件。无需为了该前提专门安装旧预览补丁。
2. 已核对正式累计更新 **KB5066791（2025-10，Windows 10 22H2 x64，约 729.7 MB）** 可将系统更新到 19045.6456，用于补齐本次兼容前提。这不是“2026 年最新更新”的声明。后续更新是否适用由微软的系统服务与授权条件决定。
3. 安装系统更新、变更已禁用的 Windows Update 服务均需用户确认及 Windows 管理员授权。保留用户手动重启，不自动重启机器。
4. 重启后检查下列命令；新版 WSL --status 成功后，再启动项目 Docker 栈。

    & 'C:\Program Files\WSL\wsl.exe' --version
    & 'C:\Program Files\WSL\wsl.exe' --status
    & 'D:\lxt\.tools\Docker\resources\bin\docker.exe' version

之后运行 D:/lxt/start-docker.cmd。Docker 目标页面是 http://127.0.0.1:8001，8000 为独立 SQLite 本地模式。

如果系统兼容前提已满足，而 WSL 自身更新下载仍失败，可按微软官方文档使用 wsl --update --web-download 从 GitHub 获取更新。这一参数不能修复旧 Windows 缺少系统补丁的问题。本机 WSL MSI 已经安装，不必反复下载或重装。

本次已经选择并验证 Hyper-V 路线；以上 WSL2 更新步骤是将来切回该后端时使用，不需要现在执行。

## 官方依据

- WSL 的 Windows 10 支持与更新前提：https://devblogs.microsoft.com/commandline/the-windows-subsystem-for-linux-in-the-microsoft-store-is-now-generally-available-on-windows-10-and-11/
- WSL 命令及 --web-download：https://learn.microsoft.com/en-us/windows/wsl/basic-commands
- KB5066791 与安装前提：https://support.microsoft.com/zh-cn/servicing/os/windows-10/2025/10/october-14-2025-kb5066791-os-builds-19044-6456-and-19045-6456
- Microsoft Update Catalog：https://www.catalog.update.microsoft.com/Search.aspx?q=KB5066791
- Docker WSL 后端：https://docs.docker.com/desktop/features/wsl/
