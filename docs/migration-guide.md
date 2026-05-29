# RoPac migration guide

**Goal:** Everything your AI needs lives inside **one `ropac` folder**. Copy that folder to another Mac, run **one setup command**, and continue with the same memory, knowledge, chat history, LLM, and voices.

---

## What lives inside `ropac/` (copy this)

| Path | What | Typical size |
|------|------|----------------|
| `data/memory.json` | Long-term facts (encrypted when enabled) | KB |
| `data/knowledge/` | Trained documents (PDF, etc.) | varies |
| `data/crypto.json` | Encryption settings | tiny |
| `data/wrapped_key.json` | Password-wrapped data key | tiny |
| `data/owner.auth` | Owner password (hash) | tiny |
| `data/chat_history.jsonl` | Chat log | varies |
| `data/settings.json` | App settings (`speak_aloud_enabled`, `tts_voice_lang` — default `"hi"` = Rohan) | tiny |
| `data/tts/` | **All voice models** (Piper, optional Parler, HF cache) | ~0.1–3 GB |
| `ollama_models/` | **LLM weights** (`roPac`, base model) | ~5–15 GB |
| `config.json` | Model name, owner name | tiny |
| `Modelfile` | RoPac personality | tiny |
| `assistant.py`, `bridge.py`, `ropac_ui/` | Code | small |

**Do not rely on** `~/.ollama`, `~/.cache/huggingface`, or `~/.roPac` after migration — RoPac keeps weights in `ollama_models/` and voices in `data/tts/`.

---

## What NOT to copy (recreate on new Mac)

| Path | Why |
|------|-----|
| `.venv/` | Python env — rebuilt by `./install.sh` (faster than copying) |
| `ropac_ui/build/` | Flutter build cache |
| `__pycache__/`, `.dart_tool/` | Caches |
| `*.part` | Partial downloads |
| `data/.vault_session/` | Temporary decrypted cache (recreated on unlock) |

---

## One-time on the **old** Mac (before copy)

Run setup so models are **inside** the folder (not only in `~/.ollama`):

```bash
cd /path/to/ropac
chmod +x install.sh
./install.sh
```

Optional — pack a zip (excludes `.venv`):

```bash
./scripts/pack_for_migration.sh
```

---

## On the **new** Mac

### 1. Install system tools (once)

- [Python 3.10+](https://python.org)
- [Ollama](https://ollama.com) — install and open the app once

### 2. Copy the folder

- USB drive, AirDrop, `scp`, or unzip `ropac-portable.zip`
- Example: `/Users/you/ropac`

### 3. One setup command

```bash
cd /Users/you/ropac
chmod +x install.sh setup.sh start.sh scripts/*.sh
./install.sh
```

This will:

1. Create `.venv` and install Python packages  
2. Link `~/.ollama/models` → `ropac/ollama_models/` (Ollama uses **your** folder)  
3. Download Piper voices only if missing  
4. Create `roPac` in Ollama only if weights are missing  
5. Write `ropac.env` and `data/ropac_root.txt` for the macOS app  
6. Install `cryptography` and enable personal-data encryption (if not already on)  

### 4. Verify

```bash
./scripts/verify_portable.sh
```

### 5. Run RoPac

**Terminal:**

```bash
./start.sh
```

**macOS app:**

```bash
./scripts/build_macos_app.sh
```

Open **Ollama**, then **RoPac.app** on Desktop → **Start model** → green **Ready**.

On first launch the app will **unlock personal data** with your **same owner password** (memory and trained files stay encrypted on disk).

Use **Chat** / **Train** tabs. Replies stream as they generate.

If the model is missing: quit Ollama (menu bar) and open it again.

---

## Checklist

| Step | Done |
|------|------|
| Copied full `ropac` folder (including `data/` + `ollama_models/`) | ☐ |
| Installed Python + Ollama on new Mac | ☐ |
| Ran `./install.sh` | ☐ |
| `./scripts/verify_portable.sh` passes | ☐ |
| Ollama shows `roPac` (`ollama list`) | ☐ |
| Chat works in app or `./start.sh` | ☐ |
| Speak aloud works (speaker icon in Chat; optional) | ☐ |

---

## Folder map (after setup)

```
ropac/
├── install.sh              ← run once per machine
├── setup.sh
├── start.sh
├── ropac.env               ← paths for app (auto-generated)
├── config.json
├── Modelfile
├── ollama_models/          ← LLM weights (COPY for offline move)
│   ├── blobs/
│   └── manifests/
├── data/
│   ├── memory.json
│   ├── knowledge/
│   ├── owner.auth
│   ├── chat_history.jsonl
│   ├── settings.json
│   ├── ropac_root.txt      ← app path marker (auto)
│   └── tts/                ← ALL voice models here
│       ├── *.onnx          ← Piper
│       ├── parler/         ← optional natural voice
│       ├── huggingface/    ← HF cache (not ~/.cache)
│       └── cache/          ← generated speech WAVs
├── ropac_ui/               ← macOS app source
└── .venv/                  ← recreate on new Mac (do not copy)
```

---

## Internet needed?

| Situation | Internet? |
|-----------|-----------|
| Copied `ollama_models/` + `data/tts/` | **No** (fully offline after setup) |
| Empty `ollama_models/` | Yes once (`ollama pull` via setup) |
| Empty `data/tts/` | Yes once (Piper download) |
| Optional Parler natural voice | Yes once (`./scripts/download_natural_tts.py`) |

---

## macOS app path

The app stores a pointer at:

`~/Library/Application Support/com.ropac.ropac_ui/ropac_root.txt`

`./install.sh` updates this to your new folder path. You can also set it in the app: **folder icon** in the **bottom** control bar → paste path → restart app.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `python: command not found` | Use `.venv/bin/python` or `python3` |
| Model not found | `./install.sh`; quit and reopen Ollama |
| App points to old path | `./install.sh` or set folder in app settings |
| Robotic voice | `.venv/bin/python scripts/download_tts_voices.py` |
| No sound in app | `./scripts/diagnose_voice.sh` — see [voice-troubleshooting.md](voice-troubleshooting.md) |
| `ollama_models` empty | Copy from old Mac or run setup with internet |
| Huge copy | Exclude `.venv` and `ropac_ui/build` |

---

## Related docs

- [portable-setup.md](portable-setup.md) — short summary  
- [offline-neural-tts.md](offline-neural-tts.md) — voice models in `data/tts/`  
- [speak-aloud-system-voice.md](speak-aloud-system-voice.md) — Piper Rohan + fallback  
- [streaming-chat.md](streaming-chat.md) — live token streaming in Chat  
- [flutter-macos-ui.md](flutter-macos-ui.md) — Desktop app layout  
- [system-design.md](system-design.md) — architecture  
