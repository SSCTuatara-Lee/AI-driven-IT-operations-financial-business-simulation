# XIAOTAO · 金融交易模拟与 AI 运维实验平台

Python / FastAPI / SQLAlchemy / MySQL / HTML + CSS + JavaScript。

## 独立资源演练与告警

平台名称现为 **XIAOTAO**。双击 `start-resource-lab.cmd` 启动独立 MySQL 演练环境，访问 http://127.0.0.1:8002/#resources；Prometheus 告警页为 http://127.0.0.1:9091/alerts。CPU、内存和专用临时容量区可通过忽略上传的 `.env.resources` 调整。详见 [资源实验说明](docs/resource-lab.md)。

默认应用 0.5 核 / 384MiB、临时区 128MiB。临时区使用内存，并不是 MySQL 磁盘缩容；已有交易环境与数据卷保留。高并发可观测真实用量与延迟，达到持续阈值才触发告警。

这是可本地运行的模拟实验平台。首期包括账户、充值、提现、转账、支付、部分退款、双边账务、对账、结构化日志、限时故障演练、证据诊断和运维知识问答。GTP 已按要求取消。

## 在新机器运行

克隆仓库后进入项目目录。需要已安装的 Python 3.12 和 Docker（含 Compose）；仓库不包含本机的 Python、Docker 安装文件、真实环境配置和运行数据。

```sh
python scripts/init_config.py
# 按需在新生成的 .env 中填写模型配置，然后启动：
docker compose up --build -d --wait
```

Linux 上如果 Python 命令名是 python3，请将第一行替换为 python3 scripts/init_config.py。打开 http://127.0.0.1:8001/，接口文档位于 http://127.0.0.1:8001/docs。未配置模型时仍可使用交易、故障演练、压测和知识检索。

下文“当前机器”指原始开发环境 D:/lxt；data/ 下的验收记录只保留在该机器，不随仓库上传。

## 当前机器状态

Python、项目依赖和 Docker Desktop 4.92.0 已安装。按用户选择，保留当前 Windows，使用 **Hyper-V 后端**。Docker Engine 29.8.0、MySQL 8.0.46 和应用容器均已启动并通过健康检查。直接访问 **http://127.0.0.1:8001/**；以后双击 start-docker.cmd 启动，脚本会等待应用和数据库健康后返回成功。

活动容器数据磁盘已放到 D:/lxt/.tools/docker-data/hyper-v/DockerDesktop.vhdx；已验证磁盘迁移、引擎重启后交易数据和压测报告保留。Windows Update 设置保持原状，无需为当前 Hyper-V 配置继续执行 wsl --update。WSL 本身仍受旧 Windows 补丁版本限制，诊断记录见 docs/docker-troubleshooting.md。

38 项自动化测试已通过；真实本地 API 与并发压测已验证，浏览器视觉检查因访问许可被拒绝而未完成。

## 在当前机器启动

独立 Python 位于 .tools/python，依赖位于 .venv，均在 D:/lxt 内。无需依赖系统 Python 或 Node.js。

双击 **start-local.cmd**，访问 http://127.0.0.1:8000。此模式使用 SQLite，数据在 data/finops.db；运行窗口按 Ctrl+C 停止。模型配置从 .env 读取，修改后重启服务。

Windows 命令行：

    cd /d D:\lxt
    .venv\Scripts\python.exe scripts\start_local.py

测试：双击 test.cmd，或运行：

    .venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider

## Docker + MySQL（本机已运行）

双击 **start-docker.cmd**。本机使用 Hyper-V，不依赖 WSL 更新成功。默认访问 http://127.0.0.1:8001，独立于 SQLite 本地模式，两套数据库不会自动互相迁移。

    docker compose up --build -d
    docker compose ps
    docker compose logs --tail=100 app

可选启用 Prometheus：

    docker compose --profile observability up -d

Prometheus 位于 http://127.0.0.1:9090；应用原始指标位于 /metrics。普通停止使用 docker compose down，保留命名卷；不要在需要保留数据时添加 -v。

数据库密码已在 .env 随机生成；文件不进入 Git。MySQL 不发布宿主机端口。Docker 活动数据位于 D:/lxt/.tools/docker-data/hyper-v/DockerDesktop.vhdx。迁移前的 C:/ProgramData/DockerDesktop/vm-data/DockerDesktop.vhdx 和 D:/lxt/.tools/docker-data/unused-new-hyperv-disk/DockerDesktop.vhdx 保留作备份，不是活动磁盘。Windows 服务与 Hyper-V 虚拟机元数据仍由系统管理，不能全部作为普通项目文件放置。

MySQL 模式已通过充值、提现、转账、支付、部分退款与上限、幂等重放、日志、响应丢失演练、证据诊断和知识问答验收。另已完成 100 并发 / 1,000 次转账，约 112.15 TPS，P95 936.98 ms，无错误且对账通过；这是一次本机短时结果。详见 data/docker-verification.json、data/loadtest-mysql-100.json 和 data/docker-persistence-verification.json。

Docker 官方安装包下载脚本为 scripts/download_docker.py，安装脚本为 scripts/install_docker.py。后者验证 Windows 数字签名，并将程序目标指定到 .tools/Docker；系统组件可能需要管理员授权和重启。脚本不执行系统重启。

## 演示步骤

1. 打开交易中心，用 ACC-1001 向 ACC-1002 转账；页面的“新交易换键”用于新的请求。
2. 保持请求正文和幂等键再次提交，回执显示幂等重放，不重复扣款。
3. 向 MCH-2001 发起支付，复制回执交易编号，选择退款并填写原支付号。
4. 在账务与对账页面运行核对，所有同币种借贷分录净额为零，账户余额与分录相符。
5. 启动“记账后响应丢失”，发起交易，收到 504 后按原幂等键查询/重试，验证只记账一次。
6. 点击 Trace ID 查看日志，进入根因分析查询该 Trace ID，核对成功记账与响应超时证据。
7. 在运维助手询问“交易超时后如何确认是否扣款？”，点击引用查看手册原文。勾选现场证据可同时分析最近 15 分钟日志。

初始账户两笔 10,000 元模拟充值也通过交易和分录入账。模拟清算账户允许负余额，其他账户不允许透支。全部金额用整数分存储，仅支持 CNY，不涉及真实资金。

## 并发压测

刷新页面，在左侧选择“并发压测”，或访问 http://127.0.0.1:8000/#loadtests 。支持转账、支付、充值、提现与同一幂等键并发重放。可配置 1–200 个并发客户端、1–10,000 次请求、1–30 秒请求超时和 1–300 秒最大发压时长。

每轮由独立 Python 进程发送真实 HTTP 请求，创建专用合成账户并准备模拟余额。采用闭环模型：每个客户端收到响应后发下一笔，不能用并发数直接推算 TPS，也不模拟固定速率的外部流量。当前各请求访问同一对专用账户，主要观察热点账户写入排队。一次只允许一个任务；切换页面不停止任务。

报告提供实时进度、峰值在途数、请求 RPS、去重后的已确认成功交易 TPS、P50/P95/P99/最大延迟、业务拒绝、HTTP/网络错误、幂等重放和结束时对账。账户准备、进程启动和结束对账不计入吞吐测量；幂等重放不计入新增交易 TPS。报告可导出 JSON，原文件保存在 data/loadtests/<任务编号>/report.json，账户、交易与日志保留。

点击“停止继续发压”或达到时限后不再发送新请求，已经发送的请求会等待返回或超时，再执行对账。因此总耗时可能超过发压时限。客户端超时可能仍在服务端记账，不能直接认定失败或用新键重试；请按错误样本的幂等键查交易，再核对账务。服务重启后不会自动继续发压，失联任务最多等待 45 秒报告更新后标记中断。

命令行也使用同一接口，例如：

    .venv\Scripts\python.exe scripts\run_loadtest.py --concurrency 100 --requests 1000
    .venv\Scripts\python.exe scripts\run_loadtest.py --concurrency 50 --requests 100 --scenario idempotency

使用 Docker 时为 CLI 加 --url http://127.0.0.1:8001；容器内发压目标仍为自身的 8000 端口。APP_TOKEN 从环境或本地 .env 读取，不写入报告。仅允许向本地 HTTP 实验服务发压；若自行修改应用监听端口，需要同步设置服务端 LOADTEST_TARGET。

可以先在“故障演练”启动限时故障，再运行压测，对比延迟、错误率、日志和根因分析。账户准备不经过故障注入，压测请求经过完整交易 API。操作手册在 docs/runbooks/concurrent-load.md。

2026-09-28 在本机 SQLite 实测：20 并发 / 200 次转账约 152.33 TPS；100 并发 / 1,000 次转账约 86.26 TPS，P95 为 2994.61 ms；200 并发 / 1,000 次转账在请求超时设为 30 秒时约 59.65 TPS，P95 为 7494.95 ms；三轮无错误且对账通过。50 并发 / 100 次同键请求只产生 1 笔交易和 99 次重放。短时实测仅说明当前本机行为，不代表持续容量或 MySQL/TDSQL 性能；单进程写锁会让交易写入排队。原始数据见 data/loadtest-20.json、data/loadtest-100.json、data/loadtest-200.json、data/loadtest-idempotency.json。

## 模型与 RAG 配置

GitHub 上传、环境变量配置及 Actions Secrets 的具体步骤见 [GitHub 与 AI 配置说明](docs/github-and-ai-config.md)。代码仓库保留 .env.example 模板，真实密钥只放在运行环境的 .env 或 Secret 中。

在本地 .env 填写以下字段，不要将真实凭据写入代码或聊天记录：

    MODEL_BASE_URL=https://your-provider.example/v1
    MODEL_API_KEY=your-key
    CHAT_MODEL=your-chat-model
    EMBEDDING_MODEL=your-embedding-model

接口约定：POST /chat/completions 与 POST /embeddings，采用兼容的 JSON 请求和响应格式。设置本地 Ollama 兼容地址时，应指向服务实际支持的 /v1 入口；容器访问宿主机模型通常需使用 host.docker.internal。

未配置模型时明确显示“知识检索模式”，提供原文而非伪造生成回答。配置聊天模型后可进行检索增强生成；配置 Embedding 后，新保存的手册建立向量。旧手册可在页面打开后重新保存以重建索引。

索引采用中文二元词/英文词 BM25，向量采用余弦相似度，并用 RRF 融合结果。向量暂存于数据库，适用于小型实验库；规模化后可替换为独立向量数据库。语义阈值是实验默认值，需要使用实际中文模型和问题集评估。网络或模型失败会降级并明确提示。聊天历史和引用快照保存在数据库中。

## 可观测与诊断边界

- JSON 运行日志保存在 data/events.jsonl，按大小轮转，同时建立数据库检索索引。
- 业务流水与审计记录分开记录，通过 Trace ID 和交易编号关联。
- Prometheus 指标含请求计数、耗时分布与交易结果；前端展示最近交易请求的实际耗时。
- 当前是单应用内事件时间线，尚未部署完整的 OpenTelemetry 分布式追踪后端、Linux 主机采集或 TDSQL 原生监控。
- 根因分析读取日志证据，输出规则候选与验证建议；不读取演练配置作为答案，不宣称证明底层因果。
- 四种故障均为应用层模拟，持续 5–300 秒，不会破坏真实数据库或操作宿主机。已进入延迟等待的请求可能在停止后完成原等待。
- 日志数据库索引、聊天和文档历史需按后续保留策略维护；当前未自动清理这些表。

## 迁移 Linux / TDSQL MySQL / CCE

Linux 可使用同一 compose.yaml。TDSQL MySQL（含赤兔管理平台的具体环境）接入需提供实例连接方式、内核版本、集中/分布式形态、TLS 和分片规则。应用通过 DATABASE_URL 连接，不能把普通 MySQL 的测试直接当作 TDSQL 已验证。

目标库连接示意（使用实际密钥管理；特殊字符须 URL 编码）：

    mysql+pymysql://USER:PASSWORD@HOST:PORT/DATABASE?charset=utf8mb4

infra/k8s.yaml 是待环境验证的 CCE/Kubernetes 迁移模板。需要将镜像推到可访问仓库、配置默认存储类和 finops-secrets，再部署。Secret 至少提供 DATABASE_URL 和 APP_TOKEN；默认 Service 仅在集群内可见。本次未创建任何云资源。

首版运行 **一个进程、一个副本**。单进程写锁与数据库事务保护资金一致性；MySQL 同时使用行锁和幂等唯一键。暂未实现多副本启动迁移锁、跨进程幂等冲突重试、TDSQL 分片设计和分布式事务验证，因此不要直接扩容副本。

本地是单操作者实验室，可通过 APP_TOKEN 增加共享令牌；尚无多用户登录、细粒度 RBAC、审批流和生产审计防篡改能力。自动修复、证券业务和基础设施级混沌演练不在此首期实现中。

## 项目文件

- app/domain.py：交易、幂等、账务和对账。
- app/faults.py / diagnostics.py：演练与证据诊断。
- app/loadtesting.py / loadtest_worker.py：压测管理、独立 HTTP 发压进程与报告。
- app/knowledge.py：索引、检索、模型适配、会话。
- app/main.py：API、鉴权、指标、页面服务。
- web/：中文操作页面，无前端构建依赖。
- docs/runbooks/：知识库初始运维手册。
- tests/：资金一致性与完整 API 流程测试。
- docs/verification.md：本次实际验证结果与未完成项。
