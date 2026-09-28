# GitHub 上传与 AI 接口环境配置

项目在启动时从环境变量读取模型配置，代码不需要包含真实密钥。

## 本机 Docker：现在可以这样配置

编辑 D:/lxt/.env 中已有的四项，不要覆盖或重建整个文件，也不要修改已经初始化的 MySQL 密码：

```dotenv
MODEL_BASE_URL=https://your-provider.example/v1
MODEL_API_KEY=replace-with-your-real-key-locally
CHAT_MODEL=your-provider-chat-model-id
EMBEDDING_MODEL=
```

- MODEL_BASE_URL：供应商提供的兼容 API 基础地址，常以 /v1 结尾；不要填写完整的 /chat/completions 路径。程序会追加 /chat/completions 或 /embeddings。
- MODEL_API_KEY：该服务的 API 密钥，在本地文件或部署平台的 Secret 中填写。
- CHAT_MODEL：供应商文档或控制台中的实际 API 模型标识。
- EMBEDDING_MODEL：可选，填写供应商支持的向量模型标识；未填写时 RAG 使用关键词检索。当前向量服务与聊天共用基础地址和密钥，不能在这里指定另一个供应商的接口地址。

此示例域名与模型名都是占位值。当前适配器使用 POST /chat/completions、POST /embeddings 及 Bearer 鉴权；如果供应商采用不同请求协议，仅修改模型名不足以接入。

保存后双击 start-docker.cmd。Compose 会把这些值通过 compose.yaml 的 environment 字段注入应用容器，配置变更会重新创建应用容器。也可在 PowerShell 中运行：

```powershell
Set-Location D:\lxt
& '.\.tools\Docker\resources\bin\docker.exe' compose up -d --no-deps --force-recreate --wait app
```

上述命令要求 MySQL 已运行，且本地已有应用镜像。只执行 docker compose restart 不会更新已有容器的环境变量。终端环境变量的优先级可能高于 .env；如果旧值一直生效，检查当前终端中是否另有同名变量。

检查 http://127.0.0.1:8001/api/config，model_configured=true 只表示地址和聊天模型配置已加载，不代表密钥有效或接口已经连通。实际验证请在“运维助手”询问“交易超时后如何确认是否扣款？”，观察是否出现模型回答；API 回执 mode=rag 表示本次调用成功生成了模型回答，warning 会提示降级原因。没有检索手册或现场证据的问题不会强行调用模型。

向量模型配置完成后，旧手册需要打开并重新保存，才会生成该模型的向量索引。

## 上传 GitHub 时保留哪些文件

提交源码、compose.yaml、Dockerfile、依赖清单、文档和空值模板 .env.example。真实 .env、.env.local 等环境文件、.tools、.venv、data 和日志不提交；本项目已为这些内容配置 .gitignore 和构建上下文忽略规则。

.gitignore 只影响未跟踪文件。如果某份密钥文件曾经被提交，新增忽略规则不能清除 Git 历史，需要另行处理历史并更换已暴露的凭据。

源码上传到 GitHub 不会让 Python 服务自动运行。克隆到 Linux 服务器后，在该服务器单独运行 python scripts/init_config.py 生成 .env，填写模型配置，再用 docker compose up --build -d 启动。网页和后台由该服务器运行；GitHub 用于保存源码。

## 使用 GitHub Actions 时如何配置

在仓库 Settings → Secrets and variables → Actions 中添加：

| 类型 | 名称 | 内容 |
| --- | --- | --- |
| Repository secret | MODEL_API_KEY | 真实模型 API 密钥 |
| Repository variable | MODEL_BASE_URL | API 基础地址 |
| Repository variable | CHAT_MODEL | 聊天模型标识 |
| Repository variable | EMBEDDING_MODEL | 可选向量模型标识 |

在已有工作流的 job 或 step 中显式注入。例如下面只是 env 片段，不是完整工作流：

```yaml
env:
  MODEL_BASE_URL: ${{ vars.MODEL_BASE_URL }}
  MODEL_API_KEY: ${{ secrets.MODEL_API_KEY }}
  CHAT_MODEL: ${{ vars.CHAT_MODEL }}
  EMBEDDING_MODEL: ${{ vars.EMBEDDING_MODEL }}
```

如果使用 Settings → Environments → production 中的环境级配置，对应 job 还必须声明 environment: production，才会使用该环境的配置。工作流在 runner 上启动的进程可以读取上述变量；远端服务器或你本机已运行的 Docker 不会自动获得这些值，部署流程还需显式把配置交给真正运行应用的环境。

普通 CI 可以继续使用现有 mock 测试，不需要真实模型密钥。当前项目没有创建 GitHub Actions 自动部署工作流；不要把一次 Actions 临时运行当成长期托管服务。

## 官方参考

- Docker 环境变量注入：https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/
- Docker 环境变量插值：https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/
- GitHub Actions Secrets：https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
- GitHub Actions Variables：https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables
