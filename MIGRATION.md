# Migrate RoPac to another computer

**Copy the whole `ropac` folder** (include `data/` and `ollama_models/`), then on the new Mac:

```bash
cd /path/to/ropac
chmod +x install.sh setup.sh scripts/*.sh
./install.sh
./scripts/verify_portable.sh
```

**Include:** `data/memory.json`, `data/knowledge/`, `data/settings.json`, `data/tts/`, `ollama_models/`  
**Skip:** `.venv/`, `ropac_ui/build/` (rebuilt by `./install.sh`)

Then: open **Ollama** → **RoPac.app** → **Start model** (bottom bar).

Full guide: **[docs/migration-guide.md](docs/migration-guide.md)**
