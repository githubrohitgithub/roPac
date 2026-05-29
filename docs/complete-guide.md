# RoPac — complete setup guide

Portable personal AI assistant. Copy the **RoPac project folder** to any Mac, run `./install.sh`, chat offline via [Ollama](https://ollama.com).

**LLM weights live in `~/.ollama/models`** (Ollama default) — **not** inside the project folder. That keeps the RoPac copy small (~300 MB without `.venv`).

**Quick refs:** [GUIDE.md](../GUIDE.md) · [migration-guide.md](migration-guide.md) · [features.md](features.md)

---

## What you are setting up

| Layer | Tool | Location |
|-------|------|----------|
| LLM chat | Ollama | `~/.ollama/models` (system default) |
| Custom personality | `Modelfile` → `roPac` | project root |
| Python brain | `assistant.py` + `bridge.py` | project root |
| Memory & RAG training | `data/memory.json`, `data/knowledge/` | `data/` |
| Speak aloud | Piper TTS | `data/tts/` |
| macOS app (optional) | Flutter | `ropac_ui/` |

All chat runs on **localhost** (`http://127.0.0.1:11434`). No cloud API required.

---

## Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| **macOS or Linux** | — | Windows: terminal only (`start.bat`) |
| **Python** | 3.10+ | `python3 --version` |
| **Ollama** | latest | [ollama.com](https://ollama.com) — keep app running |
| **Disk space** | ~8–20 GB total | Models in `~/.ollama/models` + voices in `data/tts/` |
| **RAM** | 8 GB min | 16 GB+ for 7B+ models |
| **Internet** | once | First `ollama pull` and TTS download only |

**macOS Desktop app (optional):**

- Flutter SDK + Xcode — see [flutter-macos-ui.md](flutter-macos-ui.md)

---

## Quick start (new user)

```bash
# 1. Get the project
cd ~
# copy folder or: git clone <repo-url> ropac

# 2. Install Python 3.10+ and Ollama (open Ollama app once)

# 3. One-time setup
cd ~/ropac
chmod +x install.sh setup.sh start.sh start_ui.sh scripts/*.sh
./install.sh

# 4. Terminal chat
./start.sh

# 5. macOS Desktop app (optional)
./scripts/build_macos_app.sh
# → RoPac.app on Desktop. Open Ollama first, then double-click RoPac.
```

Default owner password on first run: **`AdminRohit`** — change it:

```bash
source .venv/bin/activate
python change_password.py
```

---

## Two setup paths

### Path A — Fresh install (new machine)

RoPac downloads models into **`~/.ollama/models`** via `ollama pull` during `./install.sh`.

### Path B — Copy project from another Mac

Copy the **`ropac/` folder** (include `data/` for memory and trained files).

**Do not need** to copy `ollama_models/` — it stays empty by design.

On the new Mac:

1. Install Python + Ollama
2. Copy `ropac/` folder
3. Either **`ollama pull`** the same models, or copy **`~/.ollama/models`** from the old Mac
4. Run `./install.sh`

See [migration-guide.md](migration-guide.md).

---

## Step 1 — Get the project

**Copy folder** (USB, AirDrop, zip, scp):

```bash
scp -r user@host:~/ropac ~/ropac
```

**Git clone** (if you use a repo):

```bash
git clone <your-repo-url> ~/ropac
cd ~/ropac
```

---

## Step 2 — Install system tools

### Python 3.10+

```bash
python3 --version
```

Install from [python.org](https://python.org) if missing.

### Ollama

1. Download from [ollama.com](https://ollama.com)
2. Install and **open the Ollama app once**

Verify:

```bash
ollama --version
curl -s http://127.0.0.1:11434/api/tags
```

---

## Step 3 — One-command setup

```bash
cd ~/ropac
chmod +x install.sh setup.sh start.sh start_ui.sh scripts/*.sh
./install.sh
```

`install.sh` runs `setup.sh`:

```
┌─────────────────────────────────────────────────────────────┐
│  ./install.sh                                               │
├─────────────────────────────────────────────────────────────┤
│  1. Use ~/.ollama/models as model store (Ollama default)     │
│  2. Write ropac.env + data/ropac_root.txt (app path)        │
│  3. Create .venv + pip install -r requirements.txt          │
│  4. Enable encryption (optional, interactive)                 │
│  5. Download Piper TTS voices → data/tts/                   │
│  6. ollama pull <base_model>  (if missing)                  │
│  7. ollama create roPac -f Modelfile                        │
│  8. ollama pull nomic-embed-text  (RAG embeddings)            │
│  9. Reindex document embeddings (if trained files exist)      │
└─────────────────────────────────────────────────────────────┘
```

Expected output:

```
RoPac is ready
  Models:  /Users/you/.ollama/models
  Terminal chat:  ./start.sh
  macOS app:      ./start_ui.sh
```

---

## Step 4 — Models (where they live)

### Default: Ollama folder (outside RoPac)

| What | Path |
|------|------|
| LLM weights | `~/.ollama/models/blobs/` |
| Model registry | `~/.ollama/models/manifests/` |
| RoPac project | `~/ropac/` (code + data only, **no** 6 GB models) |

`ollama pull` and the Ollama app use this folder automatically.

### Default models (from `config.json`)

| Key | Default | Purpose |
|-----|---------|---------|
| `base_model` | `qwen2.5-coder:latest` | Underlying LLM |
| `model` | `roPac` | Custom personality (`Modelfile`) |
| `embed_model` | `nomic-embed-text` | Document search / RAG |

Image attachments use **moondream** (`ollama pull moondream`) — not configurable in `config.json`.

### Manual download

```bash
cd ~/ropac
source .venv/bin/activate

ollama pull qwen2.5-coder:latest
ollama pull nomic-embed-text
ollama create roPac -f Modelfile
```

### Verify

```bash
ollama list
ollama show roPac
ls ~/.ollama/models/blobs/
```

### Moving models out of an old RoPac copy

If you previously had models inside `ropac/ollama_models/` (older setup):

```bash
cd ~/ropac
./scripts/use_external_ollama_models.sh
```

Then **quit and reopen Ollama**, rebuild the app:

```bash
./scripts/build_macos_app.sh
```

---

## Step 5 — Models in the macOS app

Open **Model & setup** (sidebar) after building the Desktop app.

### Detected models (automatic)

- Scans **`~/.ollama/models`** for installed Ollama models
- Optionally scans **Downloads** for loose `.gguf` / `.bin` files
- Tap a model to set it as base → **Start model**

### Choose model file (manual)

- **Choose model file…** — pick any `.gguf` or `.bin` anywhere on disk
- File picker opens in `~/.ollama/models` by default
- RoPac updates `Modelfile` and rebuilds `roPac` automatically

### Switch preset models

| Model | Tier |
|-------|------|
| `gemma3:2b` | Fast · smallest |
| `llama3.2:3b` | Fast |
| `qwen2.5-coder:latest` | Code · **default** |
| `llama3.1:8b` | Balanced |
| `mistral:7b` | Balanced |
| `qwen2.5:7b` | Strong |
| `llama3.1:70b` | Largest · needs 64 GB+ RAM |

After changing `Modelfile` manually:

```bash
ollama create roPac -f Modelfile
```

In app: **Stop model** → **Start model**.

---

## Step 6 — How RoPac connects to Ollama

```
config.json          Modelfile              ~/.ollama/models/
┌──────────────┐     ┌──────────────┐       ┌─────────────────┐
│ base_model   │────▶│ FROM qwen... │       │ blobs/          │
│ model: roPac │     │ SYSTEM """   │       │ manifests/      │
│ embed_model  │     │ personality  │       │ (GGUF weights)  │
└──────────────┘     └──────────────┘       └─────────────────┘
       │                    │                       ▲
       │                    │    ollama create      │
       └────────────────────┴───────────────────────┘
                              │
                    assistant.py / bridge.py
                    → http://localhost:11434/v1
```

- **`config.json`** — model names, RAG settings, owner name
- **`Modelfile`** — personality; `FROM` line must match `base_model`
- **`bridge.py`** — Flutter app talks to Python via JSON actions

No extra wiring after `./install.sh`.

---

## Step 7 — TTS voices (speak aloud)

Included in `./install.sh`. Manual:

```bash
source .venv/bin/activate
python scripts/download_tts_voices.py
```

| Voice file | Language |
|------------|----------|
| `en_US-amy-medium.onnx` | English |
| `hi_IN-rohan-medium.onnx` | Hindi (default) |

Optional natural voice (~2 GB): `python scripts/download_natural_tts.py` — see [offline-neural-tts.md](offline-neural-tts.md).

---

## Step 8 — Verify setup

```bash
./scripts/verify_portable.sh
./start.sh -m "Hello, what is your name?"
```

---

## Step 9 — Run RoPac

### Terminal

```bash
cd ~/ropac
./start.sh
```

### macOS Desktop app

```bash
./scripts/build_macos_app.sh    # installs ~/Desktop/RoPac.app
# or developer mode:
./start_ui.sh                   # press R to hot restart
```

1. Open **Ollama** (menu bar)
2. Open **RoPac**
3. **Start model** → green **Ready**
4. **Chat** — talk; **Train** — upload documents for RAG

---

## Memory, RAG, and hard reset

### What RoPac remembers

| Data | Location |
|------|----------|
| Long-term facts | `data/memory.json` |
| Trained documents (RAG) | `data/knowledge/` |
| Chat log | `data/chat_history.jsonl` |
| Embeddings | `data/knowledge/*.embeddings.json` |

### Train tab

- Upload PDF, Word, Excel, images → owner password → **Train**
- **Forget all** — removes trained files only
- **Hard reset local data** (Danger zone) — wipes **everything**:
  - All memory facts
  - All RAG documents + embeddings
  - Chat attachment sessions
  - Chat history

Keeps: owner password, encryption, app settings, Ollama models.

### Chat commands (password required for memory)

| Command | Action |
|---------|--------|
| `save this-> <fact>` | Save fact |
| `delete this-> <text>` | Remove facts |
| `train this-> /path/to/file` | Learn from file (terminal) |

---

## Folder map (after setup)

```
ropac/                          ← copy this (~300 MB without .venv)
├── install.sh
├── config.json / Modelfile
├── assistant.py / bridge.py
├── ollama_models/              ← empty (README only — models NOT here)
├── data/
│   ├── memory.json
│   ├── knowledge/              ← RAG trained files
│   ├── owner.auth
│   ├── settings.json
│   ├── chat_history.jsonl
│   └── tts/                    ← voice models
├── ropac_ui/                   ← Flutter app source
└── .venv/                      ← recreate on new Mac (do not copy)

~/.ollama/models/               ← LLM weights (6+ GB, separate from RoPac)
├── blobs/
└── manifests/
```

---

## Migrate to another Mac

| Copy | Skip |
|------|------|
| `ropac/` folder + `data/` | `.venv/`, `ropac_ui/build/` |
| Optionally `~/.ollama/models/` | `ropac/ollama_models/` (empty) |

**On new Mac:**

```bash
cd ~/ropac
./install.sh
./scripts/build_macos_app.sh
```

If models were not copied, run `./install.sh` with internet (pulls models into `~/.ollama/models`).

Pack script (small zip, no models):

```bash
./scripts/pack_for_migration.sh
```

Full checklist: [migration-guide.md](migration-guide.md).

---

## Optional: portable models inside project

Only if you **want** models inside the RoPac folder (USB stick with everything):

```bash
ROPAC_PORTABLE_MODELS=1 ./install.sh
```

Default is **off** — use `~/.ollama/models`.

---

## Internet needed?

| Situation | Internet? |
|-----------|-----------|
| Copied `~/.ollama/models` + `data/tts/` | **No** — offline after setup |
| Fresh install, no models | Yes once (`ollama pull`) |
| Empty `data/tts/` | Yes once (Piper download) |
| New base model | Yes once for that model |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Models still in `ropac/ollama_models/` | `./scripts/use_external_ollama_models.sh` → reopen Ollama |
| Default folder shows ropac path | Rebuild app: `./scripts/build_macos_app.sh` |
| Model spinner never stops | Rebuild app (fixed in latest build) |
| `python: command not found` | Use `.venv/bin/python` |
| Ollama not running | Open Ollama app |
| Model not found | `./install.sh` → quit/reopen Ollama → **Start model** |
| App wrong folder | `./install.sh` or folder icon in app bottom bar |
| No voice | `python scripts/download_tts_voices.py` |
| Wipe all local data | Train tab → **Hard reset local data** |
| Changed personality | `ollama create roPac -f Modelfile` → Stop/Start |
| Weak document search | `ollama pull nomic-embed-text` → reindex in Train tab |

---

## Customize personality

1. Edit `Modelfile` (SYSTEM block)
2. Edit `config.json` → `owner`, `assistant_name` if needed
3. `ollama create roPac -f Modelfile`
4. Restart model in app

---

## Related docs

| Doc | Topic |
|-----|-------|
| [GUIDE.md](../GUIDE.md) | Command reference |
| [migration-guide.md](migration-guide.md) | Move to new Mac |
| [features.md](features.md) | Feature overview |
| [flutter-macos-ui.md](flutter-macos-ui.md) | macOS app |
| [encrypted-storage.md](encrypted-storage.md) | Personal data encryption |
| [streaming-chat.md](streaming-chat.md) | Live streaming |
| [system-design.md](system-design.md) | Architecture |
