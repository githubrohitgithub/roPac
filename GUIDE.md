# RoPac — command reference

Quick copy-paste commands for terminal chat, macOS UI, voice, and models.  
**All features explained:** [docs/features.md](docs/features.md) · Full docs: [docs/complete-guide.md](docs/complete-guide.md) · Flutter UI: [docs/flutter-macos-ui.md](docs/flutter-macos-ui.md)

---

## First-time setup

```bash
cd ~/ropac
chmod +x start.sh setup.sh start_ui.sh
./setup.sh
```

Installs Python venv, dependencies, Ollama model `roPac`, and **Piper TTS voices** (one-time download).

---

## Ollama (must be running)

```bash
# Open the Ollama app, or:
ollama serve

# Check
ollama list
ollama show roPac
curl http://127.0.0.1:11434/api/tags
```

Rebuild after editing `Modelfile`:

```bash
ollama create roPac -f Modelfile
```

Stop / unload model from RAM:

```bash
ollama stop roPac
```

---

## Terminal chat

```bash
cd ~/ropac
./start.sh
```

| In chat | Action |
|---------|--------|
| `remember this-> <fact>` | Save fact (owner password) |
| `forget this-> <text>` | Remove facts (password) |
| `train this-> /path/to/file` | Learn from file |
| `/memory` | Show memory |
| `/sources` | List trained files |
| `quit` or `exit` | Leave |

**CLI shortcuts:**

```bash
./start.sh -m "One question"
./start.sh --show-memory
./start.sh --train ~/Documents/notes.pdf
./start.sh --sources
./start.sh --no-auto-learn
```

**Owner password:**

```bash
cd ~/ropac && source .venv/bin/activate
python change_password.py
```

---

## macOS app (Flutter UI)

**Install RoPac.app on Desktop (release build):**

```bash
cd ~/ropac
chmod +x scripts/build_macos_app.sh
./scripts/build_macos_app.sh
```

Then double-click **RoPac** on the Desktop. Re-run the script after code changes to refresh the app.

**Developer mode (flutter run):**

```bash
cd ~/ropac
chmod +x start_ui.sh
./start_ui.sh
```

**Manual run:**

```bash
cd ~/ropac/ropac_ui
flutter pub get
flutter run -d macos
```

**Xcode from Downloads** (if needed):

```bash
export DEVELOPER_DIR="$HOME/Downloads/Xcode.app/Contents/Developer"
# or: export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
cd ~/ropac && ./start_ui.sh
```

In the app:

1. **Chat** or **Train** tab (top)
2. **Start model** (bottom bar) → green **Ready**
3. Chat — replies **stream** live; optional **speaker** for speak-aloud

See [docs/flutter-macos-ui.md](docs/flutter-macos-ui.md) · [docs/streaming-chat.md](docs/streaming-chat.md)

---

## Hot restart & reload (Flutter)

Use these while `flutter run` or `./start_ui.sh` is running in a terminal.

| Key | Action |
|-----|--------|
| **`R`** | **Hot restart** — full Dart reset (use after voice/TTS/UI code changes) |
| **`r`** | Hot reload — small UI tweaks only |
| **`q`** | Quit the app |

**Attach from a second terminal**, then press `R`:

```bash
cd ~/ropac/ropac_ui
flutter attach -d macos
```

**Full restart from shell** (not hot, but reliable):

```bash
pkill -f "ropac_ui" 2>/dev/null
cd ~/ropac && ./start_ui.sh
```

**If `flutter run` is in tmux:**

```bash
tmux send-keys -t YOUR_PANE R Enter
```

---

## Neural voice (Piper TTS)

Download / reinstall voices:

```bash
cd ~/ropac
source .venv/bin/activate
python scripts/download_tts_voices.py
```

Or full setup (includes TTS):

```bash
cd ~/ropac
./setup.sh
```

**Test speak-aloud from terminal:**

```bash
cd ~/ropac
.venv/bin/python bridge.py '{"action":"tts_status"}'
.venv/bin/python bridge.py '{"action":"speak_aloud","text":"Hello from RoPac.","prefer_piper":true}'
./scripts/diagnose_voice.sh
```

Models live in `data/tts/`. Default speak voice: **Rohan** (`data/settings.json` → `"tts_voice_lang": "hi"`).

In the app: enable the **speaker** icon in Chat. Playback uses `bridge.py` (Piper first, then macOS `say`). Details: [docs/speak-aloud-system-voice.md](docs/speak-aloud-system-voice.md)

---

## Voice input (macOS app)

- Tap mic → speak **~30–50 cm** from the laptop mic.
- Level bars must rise before speech counts.
- Pause **~5 seconds** (quiet) to auto-send, or tap stop to send.
- After code changes: **hot restart `R`**.

**System Settings (required):**

- **Privacy & Security → Microphone** — allow **RoPac** / **ropac_ui**
- **Keyboard → Dictation** — **On** (for speech-to-text)

---

## Python bridge (debug)

```bash
cd ~/ropac
.venv/bin/python bridge.py '{"action":"health"}'
.venv/bin/python bridge.py '{"action":"start_model"}'
.venv/bin/python bridge.py '{"action":"chat","message":"Hello"}'
.venv/bin/python bridge.py '{"action":"stop_model"}'
.venv/bin/python bridge.py '{"action":"tts_status"}'
.venv/bin/python bridge.py '{"action":"tts_download"}'
```

---

## Memory & files (Python)

```bash
cd ~/ropac
source .venv/bin/activate

python -c "from assistant import add_facts; add_facts(['Your fact here'])"

python assistant.py -m "What do you know about me?"
```

---

## Troubleshooting

| Problem | Command / fix |
|---------|----------------|
| Ollama not running | Open Ollama app or `ollama serve` |
| No Python venv | `cd ~/ropac && ./setup.sh` |
| Robotic voice | `python scripts/download_tts_voices.py` then **`R`** in flutter run |
| Mic / “Could not start listening” | System Settings → Mic + Dictation; hot restart **`R`** |
| UI changes not applied | **`R`** (not `r`) |
| Model not loaded | In app: **Start model**, or `bridge.py` `start_model` |
| Wrong RoPac folder in UI | Bottom bar folder icon → set path → restart app |
| No speak-aloud sound | `./scripts/diagnose_voice.sh` · [docs/voice-troubleshooting.md](docs/voice-troubleshooting.md) |

---

## Chat vs memory

- **Anyone** can chat — guests are not treated as the owner.
- **Memory** changes only with **owner password**:
  - Train tab · `remember this->` · `forget this->`
  - Chat starting with **`please remember …`** (app asks for password)
- Examples:
  - `please remember ShopMate uses Kotlin Compose`
  - `please remember` then chat — saves facts from that turn (password required)
- Normal chat does **not** auto-save memory.
- After editing `Modelfile`: `ollama create roPac -f Modelfile` then **Stop** / **Start model** in the app.

## Natural voice (Hindi / English, human-like)

Default Piper voice can sound robotic. For **ChatGPT-style** offline speech:

```bash
cd ~/ropac
./scripts/download_natural_tts.py
```

Uses **AI4Bharat Indic Parler-TTS** (~2GB, one-time). Restart the app, then use the **speaker** icon in Chat (Parler used when installed; else Piper Rohan).

Details: [docs/offline-neural-tts.md](docs/offline-neural-tts.md)

## Migrate to another Mac

Everything is inside the **`ropac` folder** (memory, LLM, voices):

1. On old Mac: `./install.sh` (puts models in `ollama_models/` + `data/tts/`)
2. Copy whole `ropac` folder (or `./scripts/pack_for_migration.sh` → zip)
3. On new Mac: install Python + Ollama → `./install.sh` → `./scripts/verify_portable.sh`

**Full guide:** [docs/migration-guide.md](docs/migration-guide.md)

| Copy | Skip |
|------|------|
| `data/`, `ollama_models/`, code | `.venv/`, `ropac_ui/build/` |

Use `.venv/bin/python` not `python` on macOS.

## Privacy

All chat, memory, and TTS run **locally**. Data is under `ropac/data/` (portable with the folder).  
RoPac does not browse the live web — use **Train** tab or `train this->` for new documents.  
First `ollama pull` / TTS download needs internet once; after that, offline.
