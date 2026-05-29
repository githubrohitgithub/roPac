# RoPac data (portable)

Everything personal stays under `data/` inside the RoPac folder.

| File / folder | Purpose |
|---------------|---------|
| `memory.json` | Long-term facts (optional AES-256-GCM — see [encrypted-storage.md](../docs/encrypted-storage.md)) |
| `knowledge/` | Trained file chunks + index (encrypted when enabled) |
| `crypto.json` | Encryption settings |
| `wrapped_key.json` | Password-wrapped data key |
| `owner.auth` | Owner password hash |
| `chat_history.jsonl` | Chat log |
| `settings.json` | UI settings (`speak_aloud_enabled`, `tts_voice_lang`) |
| `ropac_root.txt` | Path to this RoPac install (set by `./install.sh`) |
| `tts/` | Voice models — see [tts/README.md](tts/README.md) |

Copy the entire `ropac` folder to migrate. See [../docs/migration-guide.md](../docs/migration-guide.md).
