# JARVIS True Mega Architecture

This project restructures JARVIS around the Blueprint: meaning/context -> memory -> intent -> routing -> tools/AI -> execution -> verification. The mature Level-600 engine is retained as `legacy_engine.py` so existing capabilities are not discarded while the new architecture is introduced.

## Run on Windows
1. Install Python 3.11+.
2. Open CMD in the folder containing `JARVIS`.
3. `pip install -r JARVIS/requirements.txt`
4. Optional Gemini: `set GEMINI_API_KEY=YOUR_KEY`
5. Run: `python JARVIS/main.py`

Start with harmless commands such as `calculator kholo`, `notepad kholo`, or normal conversation. Risky operations should require explicit confirmation.

## Architecture
- `core/`: app, router, context, memory, planning, execution, verification, safety, logging
- `input/`: normalization
- `output/`: speech queue
- `ai/`: intent + Gemini client
- `tools/`: local computer tools
- `storage/`: SQLite memory
- `legacy_engine.py`: preserved Level-600 capabilities

This is a staged migration: not every old capability has been rewritten as a native tool yet. The legacy engine remains the compatibility layer while modules are expanded and tested.


## 1.4 Save / ASR Fix
- Adds conservative ASR aliases such as `sev`, `seve`, `sve`, `saev` -> `save`.
- Save/save-as commands are intercepted locally before the legacy engine.
- `save` uses Ctrl+S; `save as` uses Ctrl+Shift+S.
- This path intentionally does not call Gemini.


## 1.5 General Multi-Task Brain
Deterministic open/type/save/press sequences are planned and executed locally before Gemini. Voice variants for save are normalized. Sequencing cues include phir/fir/then/uske baad/after that/finally. Existing legacy engine remains as compatibility fallback.
