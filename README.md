# Local IPTV

**Version 0.2.7** · Local-first desktop-browser IPTV client

A local IPTV client built with Python, FastAPI, HTML, CSS, and vanilla JavaScript.

## Features

- Xtream Codes profiles for Live TV, Movies, Series, categories, account status, and subscription expiry when provided by the service.
- M3U/M3U8 playlist support for Live TV.
- Multiple named IPTV profiles with add, edit, remove, and top-bar server switching.

  <img width="758" height="627" alt="Screenshot 2026-10-28 at 10 49 34 PM" src="https://github.com/user-attachments/assets/537c1608-b18f-440f-a98d-ed221ac57e0c" />
  
- Home sections for Continue Watching, Movies, Series, and Live TV; drag sections to reorder them.
- Favorite channels, movies, and series, saved per IPTV profile and pinned to the top of each library's navigation tree.
- Home rows show favorites for Live TV, Movies, and Series when favorites exist; otherwise, they show the default catalog selection.
- Continue Watching saves playback progress and navigation context per profile and resumes supported streams from the saved position.

  <img width="1669" height="852" alt="Screenshot 2026-10-28 at 10 48 54 PM" src="https://github.com/user-attachments/assets/1b4825e3-4b71-4a13-8fd8-15f30c819da2" />

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

The app opens at **http://127.0.0.1:8766**. The launcher runs the server in the background and opens the default browser.

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
