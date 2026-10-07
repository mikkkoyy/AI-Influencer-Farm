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

- [AUTOMATIC1111 Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)

Then configure in `.env`:

```env
IMAGE_GEN_BASE_URL=http://localhost:7860  # AUTOMATIC1111
# or
IMAGE_GEN_BASE_URL=http://localhost:8188  # ComfyUI
```

### Voice Generation

The application uses Edge TTS by default (no API key required). Configure voice presets per influencer in the dashboard.

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
