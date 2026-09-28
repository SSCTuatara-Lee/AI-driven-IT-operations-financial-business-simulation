# 本次验证记录

日期：2026-09-28。

## 已验证

- 独立 Python 3.12.14 安装在 D:/lxt/.tools/python，项目依赖安装在 .venv。
- requirements.lock.txt 记录了实际安装的完整依赖版本。
- 32 项 pytest 测试全部通过，最近一次约 7 秒完成。
- 资金测试包括原子转账、余额不足不扣款、冻结、金额类型校验、并发不透支、并发同键去重、部分退款及累计上限。
- 额外验证对账能发现“分录仍平衡但金额不符”的错误；回滚事务不会向文件日志输出成功提交事件。
- 故障测试覆盖提交后响应丢失、停止、到期，以及诊断器不读取演练答案。
- 知识库测试覆盖新增、更新替换旧索引、删除、引用和会话历史。
- 模型适配使用 MockTransport 验证 Embedding、混合检索、生成和失败降级；未使用真实模型。
- 前端 app.js、loadtests.js 通过语法检查；HTML 的 52 个 ID 无重复，49 处静态 ID 引用有效。
- 已启动本机 8000 端口服务，真实 HTTP 验证健康检查、转账、幂等重试、对账、关联日志和知识问答通过。该验证产生了一笔 1.23 元模拟转账；结果在 data/live-verification.json。
- Docker Desktop 4.92.0 官方安装包数字签名有效，安装器退出码 0；程序主目录 D:/lxt/.tools/Docker。
- Docker CLI 29.8.0 可运行，docker compose config --quiet 通过。
- pip check 通过，无依赖冲突。

## 并发压测验证

独立发压子进程通过真实 TCP/HTTP 访问 127.0.0.1:8000。目标为当前 SQLite 数据库、一个 Uvicorn 进程，应用交易写锁开启。所有场景使用新建专用账户，账户准备和结束对账不计入吞吐量。以下为短时运行结果，未经预热或重复采样，不能作为稳定容量或不同数据库的性能结论。

| 场景 | 并发 | 请求 | 实测 RPS | 已确认 TPS | P95 ms | 错误 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 转账 | 20 | 200 | 152.33 | 152.33 | 212.20 | 0 |
| 转账 | 100 | 1,000 | 86.26 | 86.26 | 2994.61 | 0 |
| 转账 | 200 | 1,000 | 59.65 | 59.65 | 7494.95 | 0 |
| 同键重放 | 50 | 100 | 200.82 | 2.01 | 256.50 | 0 |

- 200 并发轮次采用 30 秒请求超时，最大实测延迟为 16013.32 ms；其余轮次使用 15 秒超时。不能据此保证默认超时下 200 并发无错误。
- 同键重放共 100 次成功响应，只产生 1 笔交易，其余 99 次是重放。
- 四轮均检查持久化交易数与报告去重数相同，每笔成功交易有两条分录，账务核对通过。
- 原始报告为 data/loadtest-20.json、loadtest-100.json、loadtest-200.json、loadtest-idempotency.json；汇总验证为 data/loadtest-verification.json。管理页面可查看对应历史任务。
- 新增自动化测试覆盖五种压测场景、并发实际重叠、计时窗口、主动停止/时限后在途请求排空、故障后未确认结果、业务/网络/HTTP 错误分类、参数上限、地址限制、独占运行、进程退出和重启恢复。
- 并发运维手册已保存到 docs/runbooks/concurrent-load.md，并通过 API 加入当前知识库；已验证相关问题能检索到该手册。
- HTTP 确认新页面和脚本可访问；未执行浏览器视觉与点击验收，原因见下文。

## 重启后复查（2026-09-28）

- 用户已完成 Windows 重启；HypervisorPresent=true，vmcompute 运行，Hyper-V PowerShell 模块存在。
- 系统仍是 Windows 10 Pro 22H2 19045.2006。直接调用已安装的 WSL 2.7.14 返回 WSL_E_OS_NOT_SUPPORTED，需要先补齐 Windows 系统更新。
- 系统路径上的旧 wsl.exe 不支持 --version；用户遇到的 403 更新错误不能直接证明新版 WSL 未安装。
- Windows Update 服务被禁用，未擅自更改；用户最终选择 Hyper-V 后端，完成结果见文末。
- 新增 scripts/diagnose_docker.py；结果写入 data/docker-diagnostics.json。start-docker.cmd 在已知系统版本不兼容时现在直接解释原因，不再等待引擎两分钟。

## 环境阻塞与未验证项

- 首次安装时 Docker 日志要求重启 Windows；用户现已完成，后续阻塞见上面的复查结论。
- Docker/MySQL 容器后续已使用 Hyper-V 后端启动并完成下面列出的运行验收；TDSQL 仍未接入。
- WSL 2.7.14.0 官方 MSI 已安装成功（退出码 0），SHA256 与官方发布值一致，微软数字签名有效。此前普通权限安装失败，改经 Windows 管理员授权后成功；未自动重启。
- 浏览器安全策略拒绝访问本地网页，理由为用户未授权该访问。因此未进行视觉、点击、移动端浏览器与前端端到端验收；没有通过其他浏览器或方式绕过限制。
- TDSQL 实例、赤兔环境、Linux 服务器、CCE 集群和真实模型服务均未接入；infra/k8s.yaml 仅为待验证的迁移模板。
- pytest 有一条 Starlette 关于 httpx 测试客户端的弃用提示，测试仍全部通过。

- MySQL 方言 DDL 已成功编译，包含 8 张表、幂等唯一约束与 LONGTEXT 字段；导出文件 docs/mysql-schema.sql。这只是语法生成检查，尚非目标数据库运行测试。

- 直接调用已安装的新版 WSL 可执行文件确认版本为 2.7.14.0，内核 6.18.33.2-2。发行版检查返回 WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED，与安装日志中的系统组件待重启状态一致。
- 软件主目录与项目依赖位于 D:/lxt；WSL 安装在 C:/Program Files/WSL，Docker 的系统集成也会由 Windows 安装器写入系统位置。

## Hyper-V / MySQL 完成验收（2026-09-28）

- 用户选择保留当前 Windows，切换 Docker Hyper-V 后端。WslEngineEnabled=false，com.docker.service 自动启动且运行。Windows Update 服务及系统累计补丁未修改。
- Docker Engine 29.8.0 使用 LinuxKit 7.0.12；MySQL 8.0.46 和应用容器均为 healthy。入口为 http://127.0.0.1:8001/，数据库端口未发布到宿主机。
- scripts/smoke_docker.py 使用独立合成账户通过真实 HTTP 验证充值、提现、转账、支付、部分退款、退款累计上限、幂等、日志、响应丢失后查询/重放、证据分析、知识问答和对账。记录 data/docker-verification.json。
- 在 MySQL 环境完成真实 HTTP 100 并发 / 1,000 次转账，全部成功，实际峰值在途数 100，耗时 8.917 秒，112.15 TPS，P95 936.98 ms；对账通过。原始报告 data/loadtest-mysql-100.json。这不是 TDSQL 验证，也不是长时间稳定性容量结论。
- 活动虚拟磁盘已复制到 D:/lxt/.tools/docker-data/hyper-v/DockerDesktop.vhdx（复制时 1,825,570,816 字节）。原 C 盘磁盘保留，未修改其 ACL；新目标磁盘通过 Windows 备份权限写入，Docker VM 继续使用目标路径。
- 引擎与容器重启后，原 1,000 次压测报告保留，SQL 核实 1,000 笔成功交易及 2,000 条对应分录仍在，抽查第 0、500、999 笔交易可通过 API 查询，对账通过。记录 data/docker-persistence-verification.json。
- start-docker.cmd 已实际验证：保留 Hyper-V 后端配置并等待应用、MySQL 健康后返回成功；不再要求无关的 WSL 更新。
- 之前的 32 项自动化测试针对 SQLite；本次 MySQL 验证为上述真实 API 场景与并发压测，没有声称完整 pytest 套件已在 MySQL 上运行。
