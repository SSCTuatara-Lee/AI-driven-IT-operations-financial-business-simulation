import ctypes, hashlib, json, os, subprocess, sys, time, urllib.request
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
root=Path(__file__).resolve().parents[1]
folder=root/".tools"/"installers"
folder.mkdir(parents=True,exist_ok=True)
request=urllib.request.Request("https://api.github.com/repos/microsoft/WSL/releases/latest",headers={"User-Agent":"FinOps-Lab-Setup"})
try:
    with urllib.request.urlopen(request,timeout=60) as response: release=json.load(response)
    asset=next(a for a in release["assets"] if a["name"].endswith(".x64.msi"))
except urllib.error.HTTPError as exc:
    if exc.code != 403: raise
    # Stable release and SHA256 verified from the official release assets page.
    release={"tag_name":"2.7.14"}
    asset={"name":"wsl.2.7.14.0.x64.msi","size":0,"digest":"sha256:db084e536279a59e90a26ec598d8aa8a4dff8309f41d078fd06242953ac1ebcd","browser_download_url":"https://github.com/microsoft/WSL/releases/download/2.7.14/wsl.2.7.14.0.x64.msi"}
path=folder/asset["name"]
if not path.exists() or asset["size"] and path.stat().st_size!=asset["size"]:
    print("Downloading official Microsoft WSL",release["tag_name"],flush=True)
    part=path.with_suffix(".part")
    from concurrent.futures import ThreadPoolExecutor
    url=asset["browser_download_url"]
    with urllib.request.urlopen(urllib.request.Request(url,method="HEAD"),timeout=60) as response:
        full_size=int(response.headers["Content-Length"])
    completed=min(part.stat().st_size if part.exists() else 0,full_size)
    if completed == full_size:
        completed=0  # A previous interrupted parallel download must be rechecked.
    with part.open("ab") as output: output.truncate(full_size)
    progress=[completed]
    def download_range(bounds):
        left,right=bounds
        if left>right:return
        req=urllib.request.Request(url,headers={"Range":f"bytes={left}-{right}"})
        with urllib.request.urlopen(req,timeout=60) as response,part.open("r+b") as output:
            if response.status!=206 or not response.headers.get("Content-Range","").startswith(f"bytes {left}-"):
                raise RuntimeError("Server did not honor range request; download stopped")
            output.seek(left)
            remaining=right-left+1
            while remaining:
                block=response.read(min(1024*1024,remaining))
                if not block:raise RuntimeError("Truncated range")
                output.write(block)
                remaining-=len(block)
                progress[0]+=len(block)
    chunk=(full_size-completed+3)//4
    ranges=[(completed+i*chunk,min(full_size-1,completed+(i+1)*chunk-1)) for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending=[pool.submit(download_range,bounds) for bounds in ranges]
        last=time.monotonic()
        while not all(f.done() for f in pending):
            time.sleep(1)
            if time.monotonic()-last>30:
                print("Downloaded",progress[0]//1048576,"MiB /",full_size//1048576,"MiB",flush=True)
                last=time.monotonic()
        for future in pending:future.result()
    with part.open("rb") as stream: downloaded_digest=hashlib.file_digest(stream,"sha256").hexdigest()
    if asset.get("digest") and asset["digest"]!="sha256:"+downloaded_digest:raise RuntimeError("Downloaded MSI checksum mismatch")
    part.replace(path)
with path.open("rb") as stream: digest=hashlib.file_digest(stream,"sha256").hexdigest()
if asset.get("digest") and asset["digest"]!="sha256:"+digest:raise RuntimeError("MSI checksum mismatch")
powershell=Path(os.environ.get("SystemRoot","C:/Windows"))/"System32"/"WindowsPowerShell"/"v1.0"/"powershell.exe"
command="$s=Get-AuthenticodeSignature -LiteralPath '"+str(path).replace("'","''")+"'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; @{Status=$s.Status.ToString();Signer=$s.SignerCertificate.Subject}|ConvertTo-Json -Compress"
verification=subprocess.run([str(powershell),"-NoProfile","-Command",command],capture_output=True,timeout=60,check=True)
signature=json.loads(verification.stdout.decode("utf-8-sig"))
print(json.dumps(signature),flush=True)
if signature.get("Status")!="Valid" or "Microsoft Corporation" not in signature.get("Signer",""):raise RuntimeError("MSI signature validation failed")
log=root/"data"/"wsl-install.log"
args=["/i",str(path),"/qn","/norestart","/L*v",str(log)]
print("Installing WSL system runtime, with reboot disabled",flush=True)
if ctypes.windll.shell32.IsUserAnAdmin():
    result=subprocess.run(["msiexec.exe",*args],creationflags=subprocess.CREATE_NO_WINDOW)
else:
    argument_list=", ".join("'"+value.replace("'","''")+"'" for value in args)
    elevation="try { $p=Start-Process -FilePath 'msiexec.exe' -ArgumentList @("+argument_list+") -Verb RunAs -WindowStyle Hidden -PassThru -Wait; exit $p.ExitCode } catch { Write-Error $_; exit 1 }"
    print("Windows administrator consent is required for the WSL system component.",flush=True)
    result=subprocess.run([str(powershell),"-NoProfile","-Command",elevation],creationflags=subprocess.CREATE_NO_WINDOW)
status={"release":release["tag_name"],"sha256":digest,"signature":signature,"exit_code":result.returncode,"restart_required":True}
(root/"data"/"wsl-install-result.json").write_text(json.dumps(status,indent=2),encoding="utf-8")
print(json.dumps(status),flush=True)
sys.exit(0 if result.returncode in (0,3010) else result.returncode)
