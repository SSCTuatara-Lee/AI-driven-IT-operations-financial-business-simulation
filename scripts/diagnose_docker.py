"""Read-only checks for the project's Windows Docker/WSL installation."""
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")

def decode(data):
    if b"\x00" in data[:200]:
        return data.decode("utf-16-le", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace")

def run(item):
    name, args = item
    try:
        result = subprocess.run(args, capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
        return {"check":name,"exit_code":result.returncode,"output":decode(result.stdout+result.stderr).strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"check":name,"error":str(exc)}

docker = str(ROOT/".tools/Docker/resources/bin/docker.exe")
checks = [
    ("wsl_path", ["where.exe","wsl"]),
    ("system_wsl_version", ["C:/Windows/System32/wsl.exe","--version"]),
    ("installed_wsl_version", ["C:/Program Files/WSL/wsl.exe","--version"]),
    ("wsl_status", ["C:/Program Files/WSL/wsl.exe","--status"]),
    ("wsl_distributions", ["C:/Program Files/WSL/wsl.exe","--list","--verbose"]),
    ("docker_version", [docker,"version"]),
    ("docker_context", [docker,"context","show"]),
    ("wsl_service", ["sc.exe","query","WslService"]),
    ("legacy_wsl_service", ["sc.exe","query","LxssManager"]),
    ("hypervisor_service", ["sc.exe","query","vmcompute"]),
    ("docker_processes", ["tasklist.exe","/FI","IMAGENAME eq com.docker.backend.exe","/FO","CSV"]),
]
with ThreadPoolExecutor(max_workers=6) as pool:
    results=list(pool.map(run,checks))
settings_path=Path(os.environ.get("APPDATA",""))/"Docker/settings-store.json"
if settings_path.exists():
    settings=json.loads(settings_path.read_text(encoding="utf-8-sig"))
    using_wsl=settings.get("WslEngineEnabled",settings.get("wslEngineEnabled",True))
    results.insert(0,{"check":"selected_backend","backend":"wsl2" if using_wsl else "hyper-v","data_folder":settings.get("DataFolder"),"wsl_required_for_selected_backend":using_wsl})
for result in results:
    print(json.dumps(result,ensure_ascii=False),flush=True)
(ROOT/"data/docker-diagnostics.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
