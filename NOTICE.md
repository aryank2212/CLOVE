# Third-party notices

CLOVE is © 2026 Aryan Kumar, dual-licensed under AGPL-3.0 or a commercial licence (see [COMMERCIAL.md](COMMERCIAL.md)),
except for the parts below.

## Included in this repository

| Part | Where | Licence |
|---|---|---|
| Coucou, by Louis Raillé (the code Clove Notch is built from) | `notch/` | MIT, see `notch/LICENSE` |
| Michroma font, © 2011 The Michroma Project Authors | `assistant/ui/fonts/`, `notch/public/fonts/` | SIL Open Font License 1.1 (the `OFL-Michroma.txt` next to it) |

Coucou's name, its Mochi character, its icon and its sounds are its author's and are **not** included: CLOVE
replaces them with its own mark, icon and sounds (`notch/CLOVE-FORK.md` lists every replacement, and
`notch/UPSTREAM-ASSETS-NOTICE.md` is upstream's statement about those assets).

## Installed separately

These are downloaded by the installer or on first use, under their own licences:

| Component | Used for | Licence |
|---|---|---|
| google-genai (Google Gen AI SDK) | the Gemini brains | Apache-2.0 |
| faster-whisper, CTranslate2 | speech recognition on this PC | MIT |
| Whisper models (OpenAI) | speech recognition | MIT |
| kokoro-onnx, Kokoro-82M voices | speech on this PC | MIT, Apache-2.0 |
| Ollama, Qwen 3 models | the local brain (optional) | MIT, Apache-2.0 |
| websockets, sounddevice, NumPy, Pillow, python-dotenv, python-xlib | the assistant | BSD / MIT / HPND / LGPL-2.1+ |
| Tauri, its plugins and Clove Notch's Rust and npm dependencies | Clove Notch | MIT / Apache-2.0 (see `notch/Cargo.lock`, `notch/package-lock.json`) |
| NVIDIA CUDA libraries (cuBLAS, cuDNN) | GPU speech recognition | NVIDIA's licence |

"Eurostile" is a trademark of its owner; CLOVE uses that font only if you have installed it yourself.
