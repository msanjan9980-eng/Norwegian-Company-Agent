import json, argparse
from pathlib import Path

HTML = """<!doctype html><html><head><title>Signalpost</title><style>body{font-family:system-ui;margin:20px;background:#f8f9fa}h1{color:#333}table{width:100%;border-collapse:collapse;background:white}th,td{padding:10px;text-align:left;border-bottom:1px solid #ddd}th{background:#f1f3f5}</style></head><body><h1>Signalpost</h1><table><thead><tr><th>Orgnr</th><th>Name</th><th>Form</th><th>Municipality</th><th>Revenue</th></tr></thead><tbody id="tbody"></tbody></table><script>const D=__DATA__;document.getElementById('tbody').innerHTML=D.map(function(d){return '<tr><td>'+d.org+'</td><td>'+d.name+'</td><td>'+d.form+'</td><td>'+d.muni+'</td><td>'+(d.rev&&d.rev.amount?d.rev.amount:'-')+'</td></tr>';}).join('');</script></body></html>"""

ap = argparse.ArgumentParser()
ap.add_argument("--envelopes", required=True)
ap.add_argument("--out", default=".")
args = ap.parse_args()

rows = [json.loads(l) for l in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if l.strip()]
data = []
for r in rows:
    c = r.get("claims", [])
    def v(f):
        for x in c:
            if x.get("field") == f and x.get("availability") == "available": return x.get("value")
        return None
    a = v("identity.business_address") or {}
    data.append({"org": r.get("organisation_number", ""), "name": v("identity.name") or v("identity.navn") or "", "form": v("identity.legal_form") or "", "muni": a.get("kommune", "") if isinstance(a, dict) else "", "rev": v("financials.revenue"), "claims": c})

Path(args.out).mkdir(parents=True, exist_ok=True)
Path(args.out, "index.html").write_text(HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
print(f"Wrote index.html with {len(data)} companies")
