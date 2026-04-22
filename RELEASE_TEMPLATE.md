# Release Template

## Title

`v0.1.0 - First public release`

## Body

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

### Recommended Setup Flow

1. Deploy the service
2. Open `/admin`
3. Fill in model base URL, API key, and model name there
4. Import the OpenWebUI Pipe
5. Start generating PPT in OpenWebUI

### Upstream Credits

- ppt-master: https://github.com/hugohe3/ppt-master
- OpenWebUI: https://github.com/open-webui/open-webui

### Notes

- This repository is an integration layer and depends on upstream open-source projects
- Please review upstream licenses before redistribution or commercial deployment
```
