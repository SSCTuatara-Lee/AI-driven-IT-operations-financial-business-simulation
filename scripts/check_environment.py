import ctypes, json, platform, shutil, subprocess, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
result={"python":sys.version.split()[0],"windows":platform.win32_ver(),"docker":shutil.which("docker"),"virtualization_firmware":bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(21)),"slat":bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(20))}
local_docker=Path(__file__).resolve().parents[1]/".tools"/"Docker"/"resources"/"bin"/"docker.exe"
if local_docker.exists():result["docker"]=str(local_docker)
wsl_binary="C:/Program Files/WSL/wsl.exe" if Path("C:/Program Files/WSL/wsl.exe").exists() else "wsl"
for name,args in [("wsl_version",[wsl_binary,"--version"]),("wsl_distributions",[wsl_binary,"--list","--quiet"])]:
    try:
        p=subprocess.run(args,capture_output=True,timeout=15)
        raw=p.stdout or p.stderr
        result[name]={"code":p.returncode,"output":raw.decode("utf-16-le" if b"\x00" in raw[:80] else "gbk",errors="replace")[:1800]}
    except Exception as exc: result[name]={"error":str(exc)}
Path("data").mkdir(exist_ok=True)
Path("data/environment-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2))
