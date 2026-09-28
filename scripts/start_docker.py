import json, os, shutil, subprocess, sys, time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.chdir(root)
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
subprocess.run([sys.executable,str(root/"scripts"/"init_config.py")],check=True)
docker=root/".tools"/"Docker"/"resources"/"bin"/"docker.exe"
if not docker.exists():
    found=shutil.which("docker")
    if not found:raise SystemExit("Docker is not installed. See README.md")
    docker=Path(found)
def ready():
    try:return subprocess.run([str(docker),"info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8).returncode==0
    except subprocess.TimeoutExpired:return False
if not ready():
    # A successful WSL MSI installation does not imply Windows can run it.
    # Do not repeatedly launch Desktop when its OS prerequisite is missing.
    settings_path=Path(os.environ.get("APPDATA",""))/"Docker"/"settings-store.json"
    settings=json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    if os.name=="nt" and settings.get("WslEngineEnabled",settings.get("wslEngineEnabled",True)):
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            build=int(winreg.QueryValueEx(key,"CurrentBuild")[0])
            revision=int(winreg.QueryValueEx(key,"UBR")[0])
        if build==19045 and revision<2311:
            raise SystemExit(f"Windows 10 当前版本为 19045.{revision}，缺少新版 WSL 所需系统更新。\n请先安装适用的 Windows 累积更新并手动重启；重复 wsl --update 无法补齐该系统前提。\n详情见 docs/docker-troubleshooting.md。项目脚本不会自动修改 Windows Update 设置或重启电脑。")
    desktop=root/".tools"/"Docker"/"Docker Desktop.exe"
    if not desktop.exists():raise SystemExit("Start Docker Desktop manually, then retry.")
    startup=subprocess.STARTUPINFO()
    startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow=0
    subprocess.Popen([str(desktop)],startupinfo=startup,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    print("Waiting for Docker engine; backend configuration is preserved.",flush=True)
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        if ready():break
        time.sleep(4)
    else:raise SystemExit("Docker engine is not ready. Check WSL2 and restart status in Docker Desktop.")
subprocess.run([str(docker),"compose","up","--build","-d","--quiet-pull","--wait","--wait-timeout","180"],check=True)
subprocess.run([str(docker),"compose","ps"],check=True)
print("Docker application and MySQL are healthy. Open http://127.0.0.1:8001",flush=True)
