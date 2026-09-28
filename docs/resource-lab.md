# XIAOTAO 资源受限与高并发告警实验

## 启动和调整

Windows 双击 `start-resource-lab.cmd`。其他机器安装 Docker、Compose 和 Python 3.12 后，在项目目录运行：

```sh
python scripts/resource_lab.py up
```

脚本首次生成 `.env.resources`，内含独立实验数据库的随机密码；不会覆盖主环境 `.env`。修改 `.env.resources` 中以下配置后再次启动即可应用，先停止正在运行的压测：

```dotenv
LAB_APP_CPUS=0.5
LAB_APP_MEMORY_MB=384
LAB_CAPACITY_MB=128
LAB_DB_CPUS=0.5
LAB_DB_MEMORY_MB=512
LAB_APP_PORT=8002
LAB_PROMETHEUS_PORT=9091
```

单位为 MiB。CPU 支持 0.1–4 核；应用内存支持 192–2048MiB，且必须至少比临时容量区大 192MiB；临时区支持 16–128MiB。需要 256MiB 应用内存时，把容量区一起调为 32MiB 或 64MiB。MySQL 内存可调 512–2048MiB，实验实例默认关闭 performance_schema、使用 64MiB 缓冲池和最多 40 个连接。

CPU 上限限制可用处理时间，并非绑定物理核。内存和 swap 上限设置为相同值，实验容器不能依靠额外 swap 掩盖内存不足。超出上限可能被 OOM 杀死，HTTP 客户端超时不代表交易没有记账。

容器名称固定为 `xiaotao-lab-app`、`xiaotao-lab-mysql`、`xiaotao-lab-prometheus`。底层 Compose 项目名仍为 `chengming-resources`，与主平台 `chengming-finops` 的网络和数据卷分离；原有数据卷继续复用。Docker Desktop 的项目分组因此仍可能显示旧标识。默认模型配置为空，实验不会调用收费模型接口。

- 实验平台：http://127.0.0.1:8002/#resources
- 独立告警页：http://127.0.0.1:9091/alerts
- 当前状态：`python scripts/resource_lab.py status`
- 停止实验：`python scripts/resource_lab.py down`（保留持久化数据，不带 `-v`）

## 一次完整验证

1. 资源与告警页显示真实 CPU、内存、容量和 Prometheus 规则状态。首次 CPU 百分比需等待下一次采样。
2. 并发压测设置 100 并发、10000 请求、最长 90 秒、单次超时 30 秒。受限条件下允许出现排队与错误；不要把一次短测当作持续容量。
3. 在资源页观察 CPU 使用、限流时间和延迟；告警需要满足滑动窗口与持续时间，短促突发可能只到 pending。
4. 停止发压后等待在途请求结束、核对账务，并观察告警恢复。触发/恢复日志可关联根因分析和运维问答。
5. 另做容量实验：填充 85%，持续 60 秒。容量使用率实际超过 80% 并持续 10 秒后告警，到期清理后自动恢复。填充上限 95%，只操作专用文件；不向 MySQL 数据盘写填充文件。

## 容量与监控范围

容量区是 **tmpfs 临时文件系统**，有真实容量上限，但使用内存、重建后清空；不是持久化磁盘缩容。普通 Docker 命名卷共享 Docker 虚拟机存储，不能单靠 `mem_limit` 或卷声明获得独立磁盘配额。本机当前 overlayfs/containerd 存储不能套用 overlay2 + XFS pquota 的配额示例。真正的 MySQL 磁盘配额应在后续 Linux 专用文件系统或具备配额能力的存储上另行验证，不能直接缩小已有 VHDX。

监控指标来自应用 cgroup v2，包含应用和其发压进程。MySQL 的配额真实生效，但本版未采集 MySQL 容器 CPU/内存指标；可用 `docker stats` 查看。`data` 指标是应用数据所在共享文件系统的容量，并不是应用数据文件大小。

告警阈值在 `infra/resource-alerts.yml`；修改后需重启实验 Prometheus。规则包含 CPU、内存、临时容量、共享文件系统容量、交易 P95、5xx、应用采集失败与观测到的 OOM kill。OOM/容器重启可能太快而无法被 5 秒采样捕捉，Docker 事件与状态仍需结合检查。

本次提供平台内和 Prometheus 告警。应用不可用时请查看独立告警页；Prometheus 不可用时页面显示监控失联，不将旧数据标为健康。邮件、企业微信和 Alertmanager 尚未配置。

## 本机验收记录（2026-09-28）

- 38 项 Python 自动化测试通过；Prometheus 配置与 8 条规则通过 promtool 校验；3 个前端脚本语法与 61 个 HTML ID 引用检查通过。未进行浏览器视觉验收。
- 应用真实配额为 0.5 核 / 384MiB、MySQL 为 0.5 核 / 512MiB、临时文件系统为 128MiB；两个数据库分别使用独立数据卷。
- 100 并发、计划 10000 请求、90 秒发压窗口：达到时限停止继续发压，实际完成 5543 请求，测量窗口 91.277 秒，约 60.73 已确认 TPS，客户端 P95 2179.51ms；无请求错误且账务核对通过。这不是完成了全部 10000 请求，也不是持续容量结论。
- 真实触发 FinopsCpuHigh、FinopsTradeLatencyHigh；另一次 85% 容量填充触发 FinopsCapacityHigh，经历 pending → firing → inactive，45 秒 TTL 到期后文件自动清空。触发、恢复日志及根因分析中的资源证据已核验；最终没有活动告警。
- 内存本轮未超过阈值，未触发内存告警；Docker 检查无 OOM、无容器重启。第一次容量轮询发生一次 HTTP 保持连接断开，使用新连接完成复核，没有将其误判为 OOM。
- 原平台更名前后均保留 1010 笔交易。证据保存在本机 data/resource-lab-verification.json 和 data/xiaotao-rollout.json，不上传运行数据。

## 官方参考

- [Docker Compose CPU 与内存限制](https://docs.docker.com/reference/compose-file/services/)
- [tmpfs 内存占用与生命周期](https://docs.docker.com/engine/storage/tmpfs/)
- [容器存储配额的驱动限制](https://docs.docker.com/reference/cli/docker/container/run/)
- [Prometheus 告警持续时间与状态](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
