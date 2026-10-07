# AI Influencer Farm

A local AI-powered content business management system for creating, organizing, and managing multiple virtual influencers from one dashboard.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-green)
![SQLite](https://img.shields.io/badge/SQLite-3-blue)
![Ollama](https://img.shields.io/badge/Ollama-primary%20LLM-ff6b6b)

## Features

- **Virtual Influencer Management** — Create and manage multiple AI influencer identities with profiles, bios, personalities, and visual descriptions
- **Local AI via Ollama** — Primary LLM provider with model discovery and health checks
- **Content Calendar** — Plan, schedule, and track content with draft/approved/scheduled/published states
- **Content Templates** — Reusable templates for TikTok, YouTube, Instagram, Facebook with platform-specific durations, caption formats, and hashtag strategies
- **Publishing Queue** — Persistent, restart-safe queue for platform dispatch with retry, cancel, rate limiting, and manual export fallback
- **Automation Controls** — Enable/disable automation, require approval, auto-generate content, auto-create videos, auto-schedule, max daily posts, min delay
- **Approval Workflow** — Draft → pending review → approved → scheduled → publishing → published (with reject/cancel support)
- **Video Pipeline** — End-to-end video production with script generation, TTS narration, image sequences, subtitles, and FFmpeg compositing
- **Multi-Platform Publishing** — TikTok, YouTube Shorts, and Instagram Reels support
- **Analytics Dashboard** — Track performance metrics and engagement
- **Prompt Library** — Manage content prompts and templates
- **Local Storage** — SQLite database with all data stored locally on Windows
- **Windows Native** — One-click installation with batch scripts

## Requirements

- **Windows 10/11**
- **Python 3.10+** — [Download](https://www.python.org/downloads/)
- **FFmpeg** — [Download](https://ffmpeg.org/download.html)
- **Ollama** — [Download](https://ollama.com/download)
- **Git** — [Download](https://git-scm.com/download/win)

## Installation

### One-Click Install

1. Clone or extract this repository
2. Double-click `install.bat`
3. Follow the prompts
4. Edit `.env` to configure your settings

### Manual Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/ai-influencer-farm.git
cd ai-influencer-farm

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment file
copy .env.example .env

# 5. Create required directories
mkdir storage\cookies storage\backups storage\output config\prompts logs

# 6. Pull default Ollama model
ollama pull qwen2.5:0.5b
```

## Quick Start

```bash
# 1. Activate virtual environment
.venv\Scripts\activate

# 2. Configure .env (set OLLAMA_ENABLED=true, configure models)

# 3. Start the application
python main.py
```

Or double-click `start.bat`.

Open http://localhost:8000 in your browser.

## Configuration

### Ollama (Primary AI)

Make sure Ollama is running before starting the application:

```bash
ollama serve
```

Pull the models you want to use:

```bash
ollama pull qwen2.5:0.5b
ollama pull llama3.3
```

Edit `.env` to configure:

```env
OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://localhost:11434
SCRIPT_PROVIDER_CHAIN=ollama
```

### Image Generation (Optional)

For local image generation, install one of:

**ComfyUI (recommended for advanced workflows):**
1. Clone ComfyUI: `git clone https://github.com/comfyanonymous/ComfyUI.git`
2. Install dependencies: `pip install -r ComfyUI/requirements.txt`
3. Download a Stable Diffusion model (e.g., `v1-5-pruned-emaonly.safetensors`) to `ComfyUI/models/checkpoints/`
4. Start ComfyUI: `python main.py --listen 127.0.0.1 --port 8188`

**AUTOMATIC1111 Stable Diffusion WebUI:**
1. Clone the repository: `git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git`
2. Run `webui.bat` and wait for it to start
3. The API will be available at `http://127.0.0.1:7860`

Then configure in `.env`:

```env
IMAGE_GEN_BASE_URL=http://localhost:8188  # ComfyUI
# or
IMAGE_GEN_BASE_URL=http://localhost:7860  # AUTOMATIC1111
```

**IP-Adapter Support (ComfyUI only, optional):**
1. Install the [ComfyUI IP-Adapter custom nodes](https://github.com/cubiq/ComfyUI_IPAdapter_plus)
2. Download an IP-Adapter model (e.g., `ip-adapter-plus_sd15.bin`) to `ComfyUI/models/ipadapter/`
3. Enable IP-Adapter in the Image Studio dashboard

**Note:** No models are downloaded automatically. You must manually place model files in the appropriate directories.

### Voice Generation

The application uses Edge TTS by default (no API key required). Configure voice presets per influencer in the dashboard.

### Video Production

The Video Studio supports direct video composition from selected images:

1. **Select images** — upload new images or choose from previously generated ones
2. **Optional narration** — provide text for TTS (Edge TTS fallback if Gemini TTS unavailable)
3. **Optional captions** — provide text for deterministic or Whisper-generated subtitles
4. **Configure** — set resolution (e.g. `1080x1920`), FPS, background music
5. **Create** — FFmpeg composes the final MP4 with Ken Burns effects, transitions, and optional audio

**Requirements:**
- FFmpeg must be installed and available in PATH
- Input images must be valid PNG/JPEG files
- At least one image is required

**Supported features:**
- Multiple generated images with configurable duration
- Ken Burns zoom/pan animation
- Crossfade transitions between images
- Background music mixing
- Caption/subtitle burning
- Deterministic timing when TTS timing is unavailable
- H.264/MP4 output with configurable CRF and preset
- Vertical 9:16 format optimized for TikTok/YouTube Shorts/Instagram Reels

**FFmpeg installation (Windows):**
1. Download from https://ffmpeg.org/download.html
2. Extract to a folder (e.g. `C:\ffmpeg`)
3. Add the `bin` folder to your system PATH
4. Verify with `ffmpeg -version`

### Social Media Publishing

- **TikTok**: Configure cookies in `storage/cookies/`
- **YouTube**: Set up OAuth credentials and run setup scripts
- **Instagram**: Configure webhook URL for publishing

## Directory Structure

```
AI-Influencer-Farm/
├── frontend/              # Dashboard templates and static files
├── backend/               # FastAPI backend
├── core/                  # Core models, database, and utilities
├── pipeline/              # Content production pipeline
├── config/                # Configuration files and prompts
├── storage/               # Local data storage
│   ├── viralstack.db      # SQLite database
│   ├── output/            # Generated content
│   ├── image_cache/       # Generated images cache
│   ├── backups/           # Database backups
│   └── cookies/           # Platform cookies
├── logs/                  # Application logs
├── data/                  # Data files
├── influencers/           # Influencer profiles and assets
├── generated-images/      # Generated images
├── generated-videos/      # Generated videos
├── generated-audio/       # Generated audio
├── content/               # Content drafts
├── database/              # Database files
├── scripts/               # Utility scripts
├── docs/                  # Documentation
├── main.py                # Main entry point
├── easyrun.py             # GUI launcher
├── .env                   # Environment configuration
├── requirements.txt       # Python dependencies
├── install.bat            # Windows installer
├── start.bat              # Start application
├── stop.bat               # Stop application
├── health-check.bat       # Health check
└── build.bat              # Build distribution
```

## Dashboard Pages

- **Overview** — System stats and account summaries
- **Influencers** — Create and manage virtual influencer profiles
- **Calendar** — Content calendar with draft/approved/scheduled states
- **Platforms** — Platform toggles and connection status
- **Videos** — Recent videos with status and actions
- **LLM Providers** — Model status and fallback chain
- **API Keys** — Key rotation and status
- **Emails** — Email activity (if Gmail enabled)
- **Analytics** — Performance charts and metrics
- **Audit** — Administrative action log

## Windows Scripts

| Script | Purpose |
|--------|---------|
| `install.bat` | One-click installation with dependency checks |
| `start.bat` | Start backend and open dashboard |
| `stop.bat` | Stop running backend processes |
| `health-check.bat` | Verify system health and dependencies |
| `build.bat` | Run tests and create distribution package |

## Troubleshooting

### Backend won't start

1. Check if port 8000 is already in use
2. Verify `.env` file exists and is configured
3. Run `health-check.bat` to diagnose issues

### Ollama not detected

1. Make sure Ollama is installed and running (`ollama serve`)
2. Check `OLLAMA_BASE_URL` in `.env`
3. Verify at least one model is installed (`ollama list`)

### FFmpeg not found

1. Download from https://ffmpeg.org/download.html
2. Extract to a folder
3. Add to PATH or place in application directory

### Out of disk space

The application requires free space for:
- Python virtual environment (~2 GB)
- Ollama models (~1-5 GB depending on models)
- Generated content (varies)

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
