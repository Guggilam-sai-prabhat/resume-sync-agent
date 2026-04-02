# Resume Sync Agent

A local agent that keeps your resume folder in sync with the cloud. It runs silently in the background on Windows, uploading new resumes, downloading cloud changes, and resolving conflicts automatically.

## How It Works

```
F:\resume\                          Cloud (Supabase)
├── 8byte\                    ⟷     8byte/Sai_Prabhat_Full_Stack.pdf
│   └── Sai_Prabhat_Full_Stack.pdf
├── Google\                   ⟷     Google/resume_google.pdf
│   └── resume_google.pdf
└── ...                             ...
```

On startup, the agent compares local files with the cloud using SHA-256 checksums. It then uploads, downloads, or skips each file based on deterministic rules. After the initial sync, it watches the folder in real-time for any changes.

### Sync Rules

| Scenario | Action |
|---|---|
| File only in cloud | Download to local folder |
| File only locally | Upload to cloud |
| Both exist, same checksum | Skip (already in sync) |
| Both exist, different checksum | Keep the newer version (by timestamp) |

## Prerequisites

- **Python 3.10+** — [Download](https://www.python.org/downloads/)
- **pip** (comes with Python)
- **Windows 10/11**

Verify Python is installed:

```cmd
python --version
pip --version
```

## Setup on a New Device

### Step 1 — Clone or copy the project

Copy the `resume-sync-agent` folder to `F:\resume-sync-agent\` (or your preferred location).

The folder should contain:

```
F:\resume-sync-agent\
├── main.py
├── config.py
├── api_client.py
├── sync_engine.py
├── file_indexer.py
├── checksum.py
├── watcher.py
├── install_startup.py
├── restart_agent.bat
└── requirements.txt
```

### Step 2 — Install dependencies

```cmd
cd F:\resume-sync-agent
pip install -r requirements.txt
```

### Step 3 — Configure

Open `config.py` and update these values for your setup:

```python
# Path to your local resume folder
SYNC_FOLDER: Path = Path("F:/resume")

# Your backend API URL
API_BASE_URL: str = "https://resume-sync-backend.onrender.com"
```

### Step 4 — Create your resume folder

Create the resume folder if it doesn't exist:

```cmd
mkdir F:\resume
```

Organize resumes in company subfolders:

```
F:\resume\
├── Google\
│   └── resume_google.pdf
├── Amazon\
│   └── resume_amazon.pdf
└── Startup\
    └── cover_letter.pdf
```

The subfolder name becomes the **title** in the cloud (e.g., `Google`, `Amazon`).

### Step 5 — Test manually

```cmd
cd F:\resume-sync-agent
python main.py
```

You should see output like:

```
2026-03-22 10:00:00 | INFO | sync_agent | Resume sync agent starting…
2026-03-22 10:00:00 | INFO | sync_agent | Waiting 30 seconds for network to stabilise…
2026-03-22 10:00:31 | INFO | sync_agent | API is reachable (attempt 1).
2026-03-22 10:00:32 | INFO | file_indexer | Cloud index built – 7 file(s).
2026-03-22 10:00:32 | INFO | file_indexer | Local index built – 7 file(s).
2026-03-22 10:00:32 | INFO | sync_engine | Sync started – 7 local, 7 cloud, 7 unique.
2026-03-22 10:00:32 | INFO | sync_engine | Sync cycle complete.
2026-03-22 10:00:32 | INFO | sync_agent | Agent is running.  Press Ctrl-C to stop.
```

Press `Ctrl+C` to stop.

### Step 6 — Install as startup task

Open an **Admin terminal** (right-click Command Prompt → Run as administrator):

```cmd
cd F:\resume-sync-agent
python install_startup.py install
```

Verify:

```cmd
python install_startup.py status
```

That's it! The agent will now start automatically every time you log into Windows.

## Day-to-Day Usage

### Adding a new resume

Just create a company folder and drop the PDF in:

```
F:\resume\NewCompany\my_resume.pdf
```

The agent detects it automatically and uploads it within 2 seconds.

### Supported file types

- `.pdf` (application/pdf)
- `.doc` (application/msword)
- `.docx` (application/vnd.openxmlformats-officedocument.wordprocessingml.document)

### Checking logs

```cmd
type F:\resume-sync-agent\sync_agent.log
```

Watch logs in real-time:

```cmd
powershell Get-Content F:\resume-sync-agent\sync_agent.log -Wait
```

### Restarting after code changes

Double-click `restart_agent.bat` or run:

```cmd
taskkill /IM python.exe /F
schtasks /Run /TN "ResumeSyncAgent"
```

### Managing the startup task

| Action | Command |
|---|---|
| Install | `python install_startup.py install` |
| Check status | `python install_startup.py status` |
| Remove | `python install_startup.py uninstall` |
| Force run now | `schtasks /Run /TN "ResumeSyncAgent"` |
| Stop the agent | `taskkill /IM python.exe /F` |

## Configuration Reference

All settings are in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `SYNC_FOLDER` | `F:/resume` | Local folder to sync |
| `API_BASE_URL` | `https://resume-sync-backend.onrender.com` | Backend API URL |
| `STARTUP_DELAY_SECONDS` | `30` | Wait time for network on boot |
| `NETWORK_WAIT_TIMEOUT_SECONDS` | `120` | Max time to wait for API |
| `MAX_RETRIES` | `3` | Retry count for failed API calls |
| `RETRY_BACKOFF_FACTOR` | `1.0` | Backoff multiplier (1s → 2s → 4s) |
| `WATCHER_DEBOUNCE_SECONDS` | `2.0` | Ignore duplicate file events within this window |
| `LOG_MAX_BYTES` | `5 MB` | Max log file size before rotation |
| `LOG_BACKUP_COUNT` | `3` | Number of old log files to keep |

## Log Files

Logs are stored at `F:\resume-sync-agent\sync_agent.log` with automatic rotation:

```
sync_agent.log       ← current
sync_agent.log.1     ← previous
sync_agent.log.2     ← older
sync_agent.log.3     ← oldest (auto-deleted after this)
```

Maximum disk usage: 4 files × 5 MB = 20 MB.

## Troubleshooting

### Agent not running after restart

Check if the battery setting is blocking it:

```cmd
python install_startup.py status
```

Reinstall the task (fixes battery and permission issues):

```cmd
python install_startup.py uninstall
python install_startup.py install
```

### API timeout on startup

The Render backend cold-starts and can take 30–60 seconds. The agent waits up to 120 seconds automatically. If it still fails, increase `NETWORK_WAIT_TIMEOUT_SECONDS` in `config.py`.

### Permission denied errors

Make sure the resume folder isn't open in another program (e.g., a PDF viewer locking the file). Also verify you have write access to the sync folder.

### Check if agent is running

```cmd
tasklist | findstr python
```

### Module not found errors

Reinstall dependencies:

```cmd
cd F:\resume-sync-agent
pip install -r requirements.txt
```

## Project Structure

```
sync_agent/
├── main.py              ← Entry point, orchestrates everything
├── config.py            ← All settings and tunables
├── api_client.py        ← HTTP client with retry logic
├── sync_engine.py       ← Deterministic sync rules
├── file_indexer.py      ← Builds local and cloud file indexes
├── checksum.py          ← SHA-256 computation
├── watcher.py           ← Real-time file monitoring (watchdog)
├── install_startup.py   ← Windows Task Scheduler setup
├── restart_agent.bat    ← Quick restart script
└── requirements.txt     ← Python dependencies
```