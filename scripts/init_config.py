from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
path=root/".env"
if not path.exists():
    template=(root/".env.example").read_text(encoding="utf-8")
    template=template.replace("MYSQL_PASSWORD=\n","MYSQL_PASSWORD="+secrets.token_hex(24)+"\n")
    template=template.replace("MYSQL_ROOT_PASSWORD=\n","MYSQL_ROOT_PASSWORD="+secrets.token_hex(24)+"\n")
    path.write_text(template,encoding="utf-8")
    print("Created local .env with generated database credentials; values not printed.")
else:
    print("Existing .env preserved.")
