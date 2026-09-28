from html.parser import HTMLParser
from pathlib import Path
import re
class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
    def handle_starttag(self,tag,attrs):
        value=dict(attrs).get("id")
        if value:self.ids.append(value)
root=Path(__file__).resolve().parents[1]
page=Page()
page.feed((root/"web/index.html").read_text(encoding="utf-8"))
assert len(page.ids)==len(set(page.ids)),"Duplicate HTML IDs"
script="\n".join(path.read_text(encoding="utf-8") for path in (root/"web").glob("*.js"))
references=set(re.findall(r"\$\(['\"]#([a-zA-Z][a-zA-Z0-9-]*)",script))
references={value for value in references if not value.endswith("-")}  # Exclude dynamically constructed ID prefixes.
missing=references-set(page.ids)
assert not missing,f"Missing HTML IDs: {missing}"
print(f"Static HTML references valid: {len(page.ids)} IDs, {len(references)} script references")
