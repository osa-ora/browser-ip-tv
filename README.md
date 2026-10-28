# Local IPTV

**Version 0.3.2** · Local-first desktop-browser IPTV client

A local IPTV client built with Python, FastAPI, HTML, CSS, and vanilla JavaScript.

## Features
- Continue Watching resumes series episodes with the complete season-and-episode tree restored.


- Xtream Codes profiles for Live TV, Movies, Series, categories, account status, and subscription expiry when provided by the service.
- M3U/M3U8 playlist support for Live TV.
- Multiple named IPTV profiles with add, edit, remove, and top-bar server switching.

<img width="716" height="615" alt="Screenshot 2026-10-29 at 12 20 32 AM" src="https://github.com/user-attachments/assets/e39b4e39-cd4c-4548-a0ad-e75ee4b94cec" />

- Home sections for Continue Watching, Movies, Series, and Live TV; drag sections to reorder them.
- Favorite channels, movies, and series, saved per IPTV profile and pinned to the top of each library's navigation tree. Favorite controls switch between dots and a red heart, which removes the item from favorites when clicked.
- Home rows show favorites for Live TV, Movies, and Series when favorites exist; otherwise, they show the default catalog selection.
- Continue Watching saves playback progress and navigation context per profile, resumes supported streams from the saved position, uses the parent series artwork for episode entries, and lets you remove individual entries.

<img width="1643" height="848" alt="Screenshot 2026-10-29 at 12 21 10 AM" src="https://github.com/user-attachments/assets/a6ea6ae7-5462-42e9-b523-953f6029b610" />

- Series playback groups episodes under expandable season headings in the player tree, with episode counts and the active season expanded by default.
- Daily catalog cache under `~/.local-iptv/cache/`.
- Optional application password, temporary lockout after three failed attempts, dark/light/system themes, and saved preferences.
- Local configuration under `~/.local-iptv/` (Windows: the home directory's `.local-iptv` folder).

## Run

### macOS / Linux

```bash
chmod +x run.sh
./run.sh          # Start and open the browser
./run.sh status   # Check status
./run.sh stop     # Stop the server
```

### Windows

Run these commands in Command Prompt from the extracted project directory:

```bat
run.bat
run.bat status
run.bat stop
```

The app opens at **http://127.0.0.1:8766**. The launcher runs the server in the background and opens the default browser. Use the **×** button in the app header to close Local IPTV and stop its server; use `./run.sh stop` or `run.bat stop` if needed.

### Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python run.py
```

## Requirements

- Python 3.10+
- Desktop browser with HTML5 video support
- Internet access to the configured IPTV provider

## Tests

```bash
python -m pip install pytest httpx
PYTHONPATH=. pytest -q
```

## Project layout

```text
local-iptv/
├── app/
│   ├── main.py
│   ├── templates/index.html
│   └── static/
│       ├── css/app.css
│       └── js/app.js
├── tests/test_smoke.py
├── README.md
├── requirements.txt
├── pyproject.toml
├── launcher.py
├── run.py
├── run.sh
└── run.bat
```
