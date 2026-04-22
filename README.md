# OpenWebUI PPT Service

把 `ppt-master` 接到 `OpenWebUI` 里，让你可以在聊天中生成 PPT。

这个仓库可以单独发布、单独部署。它会在本地模式下引用你已有的 `ppt-master` 仓库，在 Docker 模式下自动拉取 `ppt-master`。

## 相关项目

- `ppt-master` 原仓库: [https://github.com/hugohe3/ppt-master](https://github.com/hugohe3/ppt-master)
- `ppt-master` 作者页: [https://github.com/hugohe3](https://github.com/hugohe3)
- `OpenWebUI` 原仓库: [https://github.com/open-webui/open-webui](https://github.com/open-webui/open-webui)

## 这个项目做什么

- 保留你现有的原生 `OpenWebUI`
- 额外部署一个独立的 PPT 生成服务
- 通过 OpenWebUI 的 `Pipe` 把聊天内容转给后端
- 支持 URL、Markdown、文件上传、图片复用、AI 生图
- 支持本地测试和服务器部署

## 主要能力

- 聊天里直接触发 PPT 生成
- 读取 URL 页面内容
- 读取上传的 PDF / DOCX / Markdown 等文件
- 复用来源里的图片
- 可选 AI 生图
- 管理页可配置模型地址、Key、默认风格、默认画幅
- 下载链接使用签名 token，避免暴露服务密钥
- 自动清理历史任务，防止磁盘无限增长

## 目录

- `app/`：API、任务存储、执行器、Worker
- `openwebui_pipe/`：OpenWebUI 可导入的 Pipe
- `deployment/`：`systemd`、`nginx`、OpenWebUI 前端扩展
- `storage/`：任务、日志、导出文件
- `scripts/`：本地启动脚本

## 架构

```text
OpenWebUI
  -> Pipe
    -> PPT Service API
      -> Worker
        -> ppt-master scripts
          -> PPTX
```

## 运行模式

- 本地模式：你自己提前克隆 `ppt-master`，本服务通过 `PPT_MASTER_REPO_ROOT` 调用它
- Docker 模式：镜像构建时自动拉取 `ppt-master`

## 本地部署

### 1. 安装依赖

```bash
git clone https://github.com/<your-name>/openwebui-ppt-service.git
git clone https://github.com/hugohe3/ppt-master.git

cd /path/to/openwebui-ppt-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r /path/to/ppt-master/requirements.txt
```

### 2. 配置环境

```bash
cp .env.example .env
```

建议先只设置最基础的几项：

- `SERVICE_API_KEY`
- `PUBLIC_BASE_URL`
- `PPT_MASTER_REPO_ROOT=/absolute/path/to/ppt-master`

说明：

- `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`
- `AI 生图相关配置`
- 默认页数、默认风格、默认画幅

这些都可以在服务启动后直接去 `/admin` 页面填写，不建议第一次部署时手填一大串环境变量。

### 3. 启动 API

```bash
./scripts/dev_start.sh
```

### 4. 启动 Worker

另开终端：

```bash
cd /path/to/openwebui-ppt-service
source .venv/bin/activate
export PYTHONPATH=$PWD
python -m app_worker
```

### 5. 打开管理页并填写配置

启动后先访问：

```text
http://127.0.0.1:8099/admin
```

建议在管理页填写：

- Service API Key
- Public Base URL
- LLM Base URL
- LLM API Key
- LLM Model
- 是否启用 AI 生图
- 生图 Base URL / API Key / Model

### 6. 本地测试

JSON 任务：

```bash
curl -X POST http://127.0.0.1:8099/api/jobs/json \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -d '{
    "project_name": "demo_report",
    "source_text": "# Q3 经营复盘\n\n- 收入同比增长 18%\n- 华东区贡献主要增量\n- 新客成本上升，复购改善\n",
    "canvas_format": "ppt169",
    "page_count": 6,
    "style_objective": "general_consulting"
  }'
```

文件上传：

```bash
curl -X POST http://127.0.0.1:8099/api/jobs \
  -H "X-API-Key: change-me" \
  -F "project_name=demo_pdf" \
  -F "canvas_format=ppt169" \
  -F "page_count=8" \
  -F "style_objective=general_consulting" \
  -F "file=@/absolute/path/to/demo.pdf"
```

查看状态：

```bash
curl -H "X-API-Key: change-me" http://127.0.0.1:8099/api/jobs/<job_id>
curl -H "X-API-Key: change-me" http://127.0.0.1:8099/api/jobs/<job_id>/logs
```

下载结果：

```bash
curl -L -H "X-API-Key: change-me" \
  http://127.0.0.1:8099/api/jobs/<job_id>/download/native \
  -o result.pptx
```

## 服务器部署

### 1. 放到服务器

建议目录：

```bash
/opt/openwebui-ppt-service
```

### 2. 配置 `.env`

```bash
cd /opt/openwebui-ppt-service
cp .env.example .env
```

重点配置：

- `SERVICE_API_KEY`
- `PUBLIC_BASE_URL`
- `PPT_MASTER_REPO_ROOT=/opt/ppt-master`
- `PPT_MASTER_REPO_URL=https://github.com/hugohe3/ppt-master.git`
- `PPT_MASTER_REPO_REF=main`

可选配置：

- `EXPORT_RETENTION_DAYS=7`
- `CLEANUP_INTERVAL_SECONDS=3600`
- `MAX_UPLOAD_MB=50`

说明：

- 模型接口、模型 Key、模型名、生图配置，推荐在 `/admin` 页面里填写
- `.env` 更适合放基础运行参数和服务级配置

### 3. Docker Compose 启动

```bash
docker compose up -d --build
```

说明：

- Docker 镜像会自动克隆 `ppt-master`
- 如果你要锁定上游版本，可以修改 `PPT_MASTER_REPO_REF`

### 4. 健康检查

```bash
curl http://127.0.0.1:8099/healthz
```

### 5. 进入管理页完成模型配置

部署完成后优先访问：

```text
https://你的域名/admin
```

在这里填写：

- Service API Key
- Public Base URL
- LLM Base URL / API Key / Model
- AI 生图开关
- 生图 API Key / Base URL / Model
- 默认风格 / 默认页数 / 默认画幅

### 6. 反代

参考：

- `deployment/nginx/ppt-master.conf`

## OpenWebUI 接入

### 导入 Pipe

1. 打开 OpenWebUI 后台
2. 进入 `Functions`
3. 导入 `openwebui_pipe/ppt_master_pipe.py`
4. 在 Pipe 的 Valves 里填：
   - `service_url`
   - `service_api_key`
   - `confirmation_mode`
   - `canvas_format`
   - `page_count`
   - `style_objective`

推荐流程：

1. 先部署 PPT Service
2. 先去 `/admin` 填好模型配置
3. 再导入 Pipe
4. 最后在 OpenWebUI 里测试生成

### 使用方式

在 OpenWebUI 里选择 `PPT Master Service`，直接输入：

- 主题
- URL
- Markdown
- 文件素材
- 你想要的页数、风格、图片策略

### 确认模式

- `auto`：直接生成
- `lite`：轻确认
- `full`：完整八项确认

## OpenWebUI 前端扩展板

本项目还提供了一个仅对 PPT 聊天生效的前端面板：

- `deployment/openwebui/loader.js`
- `deployment/openwebui/custom.css`

作用：

- 在 PPT 聊天里直接选参数
- 自动注入确认模式、页数、风格、图片策略
- 支持隐藏后从浮窗重新打开

部署示例：

```bash
docker cp deployment/openwebui/loader.js open-webui:/app/build/static/loader.js
docker cp deployment/openwebui/custom.css open-webui:/app/build/static/custom.css
docker restart open-webui
```

## 安全说明

- 建议只对内网或可信网段开放管理页
- `SERVICE_API_KEY` 不要写进公开仓库
- 下载链接使用签名 token，不要暴露真实服务密钥
- OpenWebUI 镜像升级后，前端注入文件可能需要重新覆盖

## 常见问题

### 1. 这是第二套 OpenWebUI 吗

不是。`OpenWebUI` 还是你原来的那套，这里只是给它加了一个 PPT 后端能力。

### 2. 支持上传文件吗

支持。`Pipe` 会尽力把附件直传给后端。

### 3. 会自动清理垃圾吗

会。Worker 会按保留天数清理历史任务和导出文件。

### 4. 能不能只本地跑

可以，先跑 API + Worker，再在浏览器里访问 `/admin` 测试。

## 许可

本项目基于 `ppt-master` 和 `OpenWebUI` 的开源能力做集成，请同时遵守上游项目的许可证和使用条款。
