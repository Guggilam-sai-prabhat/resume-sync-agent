"""
Register (or unregister) the resume sync agent as a Windows scheduled task
that runs automatically at user logon.

Usage (run from an elevated / admin terminal):
    python install_startup.py install
    python install_startup.py uninstall
    python install_startup.py status
"""

import subprocess
import sys
import os
from pathlib import Path

TASK_NAME = "ResumeSyncAgent"
AGENT_DIR = Path("F:/resume-sync-agent")
MAIN_SCRIPT = AGENT_DIR / "main.py"
PYTHON = Path(sys.executable)

LOG_FILE = AGENT_DIR / "sync_agent.log"


def install():
    """Create a scheduled task that launches the agent at every user logon."""
    python = str(PYTHON)

    # First delete any existing task to start clean.
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )

    # Use XML to create the task – this gives us full control over
    # battery settings and working directory, which schtasks /Create
    # flags don't fully support.
    task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT10S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{python}"</Command>
      <Arguments>"{MAIN_SCRIPT}"</Arguments>
      <WorkingDirectory>{AGENT_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

    # Write the XML to a temp file.
    xml_path = AGENT_DIR / "_task.xml"
    xml_path.write_text(task_xml, encoding="utf-16")

    cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"]

    print(f"Registering task '{TASK_NAME}'...")
    print(f"  Python  : {python}")
    print(f"  Script  : {MAIN_SCRIPT}")
    print(f"  Log file: {LOG_FILE}")
    print(f"  Battery : runs on AC and battery")
    print(f"  Restart : retries up to 3 times on failure")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up temp file.
    xml_path.unlink(missing_ok=True)

    if result.returncode == 0:
        print(f"\nTask '{TASK_NAME}' installed successfully!")
        print("The sync agent will start automatically at next logon.")
        print(f"\nTo run it now:  schtasks /Run /TN \"{TASK_NAME}\"")
    else:
        print(f"Failed to create task:\n{result.stderr}")
        print("Make sure you're running this from an admin terminal.")
        sys.exit(1)


def uninstall():
    """Remove the scheduled task."""
    cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    print(f"Removing task '{TASK_NAME}'...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"Task '{TASK_NAME}' removed.")
    else:
        print(f"Failed to remove task:\n{result.stderr}")
        sys.exit(1)


def status():
    """Check whether the task exists and its current state."""
    cmd = ["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"Task '{TASK_NAME}' is registered:\n")
        for line in result.stdout.splitlines():
            line = line.strip()
            if any(k in line for k in ("Status", "Task To Run", "Next Run", "Last Run", "Last Result", "Start In")):
                print(f"  {line}")
    else:
        print(f"Task '{TASK_NAME}' is NOT registered.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "uninstall", "status"):
        print("Usage: python install_startup.py [install | uninstall | status]")
        sys.exit(1)

    action = sys.argv[1]
    if action == "install":
        install()
    elif action == "uninstall":
        uninstall()
    elif action == "status":
        status()


if __name__ == "__main__":
    main()