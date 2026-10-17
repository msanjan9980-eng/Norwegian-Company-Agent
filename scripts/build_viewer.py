from pathlib import Path
import argparse
import json

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>Signalpost</title>
<style>body{font-family:system-ui;margin:0;padding:24px;background:#fafafa}input{width:100%;max-width:400px;padding:10px;border:1px solid #ddd;border-radius:6px;margin-bottom:16px}table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px}th,td{padding:10px;text-align:left;border-bottom:1px solid #eee}th{background:#f9f9f9;font-size:11px;text-transform:uppercase}tr:hover{background:#f0f7ff;cursor:pointer}#m{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);padding:5% 0;overflow-y:auto}#i{background:#fff;margin:0 auto;width:90%;max-width:1000px;padding:24px;border-radius:8px}pre{white-space:pre-wrap;font-family:monospace;background:#f5f5f5;padding:12px;font-size:12px;max-height:400px;overflow-y:auto}</style></head><body>
<h1>Signalpost</h1>
<input id="q" placeholder="Search name, orgnr, municipality...">
<table><thead><tr><th>Orgnr</th><th>Name</th><th>Form</th><th>Municipality</th><th>Revenue</th><th>Employees</th></tr></thead><tbody id="t"></tbody></table>
<div id="m"><div id="i"><button onclick="document.getElementById('m').style.display='none'">Close</button><div id="b"></div></div></div>
<script>
const D = __DATA__;
function f(n){if(n==null||n==="")return"-";const v=Number(n);if(isNaN(v))return n;if(Math.abs(v)>=1e6)return(v/1e6).toFixed(1)+"M";if(Math.abs(v)>=1e3)return(v/1e3).toFixed(0)+"K";return v}
function e(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function r(rows){
  document.getElementById("t").innerHTML = rows.map(x =>
    "<tr onclick=\"o('"+x.org+"')\"><td>"+e(x.org)+"</td><td><b>"+e(x.name)+"</b></td><td>"+e(x.form)+"</td><td>"+e(x.muni)+"</td><td>"+f(x.rev)+"</td><td>"+e(x.emp)+"</td></tr>"
  ).join("");
}
function o(org){
  const x = D.find(y => y.org === org);
  if (!x) return;
  let h = "<h2>"+e(x.org)+" — "+e(x.name)+"</h2>";
  h += "<h3>Claims ("+x.claims.length+")</h3><table><tr><th>Field</th><th>Value</th><th>Avail</th></tr>";
  for (const c of x.claims) {
    const v = typeof c.value === "object" ? JSON.stringify(c.value) : String(c.value || "");
    h += "<tr><td>"+e(c.field)+"</td><td style=\"word-break:break-all\">"+e(v)+"</td><td>"+e(c.availability)+"</td></tr>";
  }
  h += "</table>";
  document.getElementById("b").innerHTML = h;
  document.getElementById("m").style.display = "block";
}
document.getElementById("q").addEventListener("input", ev => {
  const q = ev.target.value.toLowerCase();
  r(D.filter(x => !q || (x.name||"").toLowerCase().includes(q) || (x.org||"").includes(q) || (x.muni||"").toLowerCase().includes(q)));
});
r(D);
</script></body></html>"""

import json
from pathlib import Path

rows = [json.loads(l) for l in Path("out/cited-envelopes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

def v(c, f):
    for x in c:
        if x.get("field") == f and x.get("availability") == "available":
            return x.get("value")
    return None

data = []
for r in rows:
    c = r.get("claims", [])
    a = v(c, "identity.business_address") or {}
    rv = v(c, "financials.revenue")
    data.append({
        "org": r["organisation_number"],
        "name": v(c, "identity.name") or v(c, "identity.navn") or "",
        "form": v(c, "identity.legal_form") or "",
        "muni": a.get("kommune", "") if isinstance(a, dict) else "",
        "rev": rv.get("amount") if isinstance(rv, dict) else rv,
        "emp": v(c, "identity.employees"),
        "claims": c,
    })

tpl = Path("template.html").read_text(encoding="utf-8")
Path("index.html").write_text(tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str)), encoding="utf-8")
print(f"OK: wrote index.html with {len(data)} companies")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelopes", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rows = [json.loads(l) for l in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if l.strip()]
    data = []
    for r in rows:
        c = r.get("claims", [])
        addr = v(c, "identity.business_address") or {}
        rev = v(c, "financials.revenue")
        data.append({
            "org": r["organisation_number"],
            "name": v(c, "identity.name") or v(c, "identity.navn") or "",
            "form": v(c, "identity.legal_form") or "",
            "muni": addr.get("kommune", "") if isinstance(addr, dict) else "",
            "rev": rev.get("amount") if isinstance(rev, dict) else rev,
            "emp": v(c, "identity.employees"),
            "claims": c,
        })

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_out = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str))
    (out_dir / "index.html").write_text(html_out, encoding="utf-8")
    print(f"Wrote {out_dir}/index.html with {len(data)} companies.")

if __name__ == "__main__":
    main()
