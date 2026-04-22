# Publishing Guide

## Recommended Repository Name

`openwebui-ppt-service`

## Suggested Short Description

Connect ppt-master to OpenWebUI so users can generate PPT from chat, URLs, and uploaded files.

## Suggested Chinese Description

把 ppt-master 接入 OpenWebUI，让用户可以通过聊天、URL 和文件上传来生成 PPT。

## Suggested Long Description

An independent PPT generation backend for OpenWebUI, powered by ppt-master. It supports chat-driven PPT creation, URL ingestion, file upload, source image reuse, optional AI image generation, and signed download links. Includes local development setup, Docker deployment, and OpenWebUI Pipe integration.

## Suggested GitHub Topics

`openwebui`, `ppt`, `powerpoint`, `pptx`, `presentation`, `fastapi`, `docker`, `llm`, `ai`, `openai-compatible`

## Suggested Repository Intro

### English

OpenWebUI PPT Service is an independent PPT generation backend powered by ppt-master. It integrates with OpenWebUI through a Pipe, supports URL and file ingestion, source image reuse, optional AI image generation, signed downloads, and an admin page for model configuration.

### Chinese

OpenWebUI PPT Service 是一个基于 ppt-master 的独立 PPT 生成后端。它通过 Pipe 接入 OpenWebUI，支持 URL 和文件导入、来源图片复用、可选 AI 生图、签名下载链接，以及通过 `/admin` 页面管理模型配置。

## Before Publishing

1. Remove any real keys from `.env`
2. Keep only `.env.example` in the repo
3. Review `README.md`
4. Review `NOTICE.md`
5. Choose and add a license file if you want the repository to be publicly reusable

## Git Commands

If you want to publish this directory as a new standalone repo:

```bash
cd /path/to/openwebui-ppt-service
git init
git branch -M main
git add .
git commit -m "Initial release: OpenWebUI PPT Service"
git remote add origin git@github.com:<your-name>/openwebui-ppt-service.git
git push -u origin main
```

If you use HTTPS instead of SSH:

```bash
git remote add origin https://github.com/<your-name>/openwebui-ppt-service.git
git push -u origin main
```

## GitHub CLI

If you have `gh` installed:

```bash
cd /path/to/openwebui-ppt-service
gh repo create openwebui-ppt-service \
  --public \
  --source=. \
  --remote=origin \
  --push \
  --description "Connect ppt-master to OpenWebUI so users can generate PPT from chat, URLs, and uploaded files."
```

## Recommended First Release Notes

```text
Initial public release of OpenWebUI PPT Service.

- Connects OpenWebUI to ppt-master
- Supports text, URL, and file-based PPT generation
- Supports OpenWebUI Pipe integration
- Includes local run guide and server deployment guide
- Includes admin page and signed artifact downloads
```

## Suggested GitHub Release Title

```text
v0.1.0 - First public release
```

## Suggested GitHub Release Body

```markdown
## OpenWebUI PPT Service v0.1.0

First public release of the OpenWebUI PPT integration service.

### Highlights

- Connects OpenWebUI to ppt-master
- Supports generating PPT from chat text, URLs, and uploaded files
- Supports OpenWebUI Pipe integration
- Supports source image reuse and optional AI image generation
- Includes an `/admin` page for model configuration
- Includes Docker deployment and local development guide
- Includes signed download links and automatic cleanup for old jobs

### Upstream Credits

- ppt-master: https://github.com/hugohe3/ppt-master
- OpenWebUI: https://github.com/open-webui/open-webui

### Notes

- This repository is an integration layer and depends on upstream open-source projects
- Please review upstream licenses before redistribution or commercial deployment
```

## Suggested GitHub About Fields

Homepage:

```text
https://github.com/<your-name>/openwebui-ppt-service
```

Website:

```text
https://<your-domain>
```

## Suggested Announcement Copy

```text
Open-sourced my OpenWebUI PPT integration service. It connects OpenWebUI with ppt-master, supports chat-to-PPT generation, file upload, URL ingestion, optional AI image generation, and independent deployment. Feedback is welcome.
```
