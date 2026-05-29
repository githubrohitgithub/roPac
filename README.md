# RoPac — portable personal AI

Copy this **entire folder** to any laptop (including `ollama_models/` and `data/`). One command configures everything: **`./install.sh`**. Runs offline via [Ollama](https://ollama.com).

**Migrate to another Mac:** [docs/migration-guide.md](docs/migration-guide.md) · [MIGRATION.md](MIGRATION.md)

**Feature overview:** [docs/features.md](docs/features.md) · **Commands:** [GUIDE.md](GUIDE.md) · **System design:** [docs/system-design.md](docs/system-design.md) (architecture + security diagrams) · **macOS app:** [docs/flutter-macos-ui.md](docs/flutter-macos-ui.md)

---

## Requirements (once per machine)

1. [Python 3.10+](https://python.org)
2. [Ollama](https://ollama.com) — keep the app running
3. **macOS app only:** Flutter SDK + Xcode (see [GUIDE.md](GUIDE.md))

---

## Quick start — one-time setup

**Mac / Linux** (after copying the folder):

```bash
cd ~/ropac
chmod +x install.sh setup.sh start.sh start_ui.sh
./install.sh    # Python + Ollama link + model — once per machine
```

## Quick start — terminal chat

```bash
./start.sh
```

**Windows:**

```cmd
cd path\to\ropac
start.bat
```

First run creates `.venv`, installs Python deps, pulls the base model, builds `roPac`, and opens chat.

---

## Quick start — macOS app (Chat + Train)

**Desktop app (double-click):**

```bash
cd ~/ropac
chmod +x scripts/build_macos_app.sh
./scripts/build_macos_app.sh
```

Creates **`RoPac.app` on your Desktop**. Open **Ollama** first, then double-click **RoPac**.

**In the app:**

| Area | What |
|------|------|
| **Left sidebar** | **Chat** / **Train**, **Start model** / **Stop model** (collapses after ready for full chat space) |
| **Chat** | Streaming replies, **Ask me anything** input, click anywhere to focus and type |
| **Chat bar** | **Speaker** — read replies aloud (offline **Piper Rohan** by default) |
| **Train** | Upload a file + owner password (updates memory from the document) |
| **Empty chat** | AI core animation when model is ready (static when stopped) |

**Developer mode (hot reload):**

```bash
cd ~/ropac
./start_ui.sh
```

Press **`R`** in the terminal to hot restart (see [GUIDE.md](GUIDE.md)).

---

## What gets installed (`./setup.sh`)

- Python packages: `openai` (Ollama API), `pypdf`, `openpyxl`, `python-docx`, `piper-tts`, `onnxruntime`
- Ollama model `roPac` (from `Modelfile` + `config.json`)
- Piper TTS voices under `data/tts/` (Amy English, **Rohan Hindi** — default for speak-aloud)
- Optional: [Indic Parler-TTS](docs/offline-neural-tts.md) for more natural speech (`./scripts/download_natural_tts.py`)

`./install.sh` runs the same setup as `./setup.sh` (portable path links, venv, models).

---

## Speak aloud & voice

- Turn on the **speaker** icon in Chat (saved in `data/settings.json`).
- Default voice: **Rohan** (`tts_voice_lang`: `"hi"`). Set `"en"` for Amy.
- Playback goes through `bridge.py` → Piper WAV, with macOS `say` fallback if needed.
- No internet at runtime after voices are downloaded.

**If you hear nothing:** `cd ~/ropac && ./scripts/diagnose_voice.sh` — see [docs/voice-troubleshooting.md](docs/voice-troubleshooting.md) · [docs/speak-aloud-system-voice.md](docs/speak-aloud-system-voice.md)

---

## Memory commands (password required)

Use these in the **macOS app Chat** or **terminal** (`./start.sh`). The app asks for the **owner password** before saving or deleting memory.

| Command | Action |
|---------|--------|
| `save this-> <fact>` | Save a fact to long-term memory |
| `delete this-> <text>` | Remove matching facts |
| `save->` / `delete->` | **Invalid** — must include **this** |
| `please save …` | Save from natural phrasing (password in app) |

**Train tab:** pick a file, enter password, tap **Train file** — document chunks and extracted facts are stored.

**Terminal only:**

| Input | Action |
|-------|--------|
| `train this-> /path/to/file` | Learn from PDF, Excel, Word, text, code, etc. |
| `remember this->` / `forget this->` | Legacy aliases for `save` / `delete` |
| `/memory` | Show saved memory |
| `/sources` | List trained files |
| `quit` / `exit` | Leave chat |

**CLI without opening chat:**

```bash
./start.sh -m "One question"
./start.sh --show-memory
./start.sh --train ~/Documents/notes.pdf
./start.sh --sources
```

Change owner password:

```bash
source .venv/bin/activate
python change_password.py
```

Default password on first setup: `AdminRohit` (change this).

---

## Who can chat vs who can change memory

- **Anyone** can chat — guests are **not** assumed to be the owner.
- **Memory** changes only with the **owner password**: `save this->`, `delete this->`, **Train** file upload, or `please save …` in chat.
- Normal chat does **not** auto-save to memory (the model will not “fix memory” from casual corrections).

---

## Encrypted personal data (automatic)

`./install.sh` installs **cryptography** and offers to **encrypt** `data/memory.json` and `data/knowledge/` (config: `encrypt_personal_data` in `config.json`).

**macOS app:** on launch → enable (once) + **unlock** with owner password → fast session cache → **wiped on quit**.

**New Mac:** copy the whole `ropac` folder → `./install.sh` → open app → unlock with the **same** owner password.

See [docs/encrypted-storage.md](docs/encrypted-storage.md) · [migration-guide.md](docs/migration-guide.md)

---

## Your data (travels with the folder)

| Path | Purpose |
|------|---------|
| `data/memory.json` | Long-term facts (plain or encrypted) |
| `data/owner.auth` | Owner password hash (not plain text) |
| `data/knowledge/` | Trained file chunks |
| `data/crypto.json` | Encryption on/off (if enabled) |
| `data/chat_history.jsonl` | Chat log |
| `data/settings.json` | App settings (speak aloud, voice language) |
| `data/tts/` | All voice models (Piper, optional Parler) — not `~/.cache` |
| `ollama_models/` | LLM weights — not only `~/.ollama` |
| `config.json` | Model name, owner, Ollama URL |
| `ropac_ui/` | Flutter macOS app |

**Migrate:** copy whole folder → `./install.sh` on new Mac.  
Guide: [docs/migration-guide.md](docs/migration-guide.md) · short: [MIGRATION.md](MIGRATION.md)

Skip when copying: `.venv/`, `ropac_ui/build/` (recreated by `./install.sh`).

**More docs:** [features](docs/features.md) · [streaming chat](docs/streaming-chat.md) · [portable setup](docs/portable-setup.md) · [complete guide](docs/complete-guide.md)

---

## Customize personality / model

Edit `Modelfile` and/or `config.json`, then:

```bash
ollama create roPac -f Modelfile
```

Restart the model in the app (**Stop** → **Start**) or run `./start.sh` again.

---

## Manual setup (no chat)

```bash
./setup.sh
source .venv/bin/activate
python assistant.py -m "Hello"
```

---

## Privacy

Everything runs on **localhost**. No cloud APIs for chat or memory.  
First-time `ollama pull` and TTS download need internet once; after that, offline.
