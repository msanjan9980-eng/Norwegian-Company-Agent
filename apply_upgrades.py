from pathlib import Path
import ast, re, sys

def patch(path, old, new, label):
    p = Path(path)
    if not p.exists():
        print(f"  MISSING {path}"); return False
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"  ALREADY {label}"); return True
    if old not in text:
        print(f"  NO-MATCH {label} in {path}"); return False
    text = text.replace(old, new, 1)
    if path.endswith(".py"):
        ast.parse(text)
    p.write_text(text, encoding="utf-8", newline="\n")
    print(f"  PATCHED {label}")
    return True

print("Applying upgrades...")

# 1. Registry snapshot argument in run.py
patch(
    "run.py",
    '    batch = [\n        "uv", "run", "python", "-X", "utf8", "scripts/run_competition_batch.py",',
    '    snapshot = env.get("SIGNALPOST_REGISTRY_SNAPSHOT", "").strip()\n    batch = [\n        "uv", "run", "python", "-X", "utf8", "scripts/run_competition_batch.py",',
    "run.py registry env var"
)
patch(
    "run.py",
    '    if _run("[2/9] batch runner", batch, env):',
    '    if snapshot:\n        batch.extend(["--bulk", snapshot])\n    if _run("[2/9] batch runner", batch, env):',
    "run.py --bulk passthrough"
)

# 2. Claim spans in depth_claims.py
# Add claim_span to expand_registry
patch(
    "src/norway_company_agent/depth_claims.py",
    '        claims.append({\n            "field": f"{prefix}.{k}",\n            "value": v,',
    '        claims.append({\n            "field": f"{prefix}.{k}",\n            "value": v,\n            "claim_span": f"key:{k}",\n            "extraction_method": "registry_mapping",',
    "depth_claims.py registry span"
)
# Add claim_span to expand_financials
patch(
    "src/norway_company_agent/depth_claims.py",
    '        claims.append({\n            "field": f"financials.{metric}",\n            "value": {"amount": amount, "currency": currency, "year": year},',
    '        claims.append({\n            "field": f"financials.{metric}",\n            "value": {"amount": amount, "currency": currency, "year": year},\n            "claim_span": f"financials:{year}:{metric}",\n            "extraction_method": "financial_mapping",',
    "depth_claims.py financial span"
)

# 3. Enforce claim_span in citation_envelope.py
patch(
    "src/norway_company_agent/citation_envelope.py",
    '        if c.get("availability") == "available" and not c.get("evidence_ids"):\n            problems.append(f"claims[{i}] available but no evidence_ids")',
    '        if c.get("availability") == "available" and not c.get("evidence_ids"):\n            problems.append(f"claims[{i}] available but no evidence_ids")\n        if c.get("availability") == "available" and not c.get("claim_span"):\n            problems.append(f"claims[{i}] available but no claim_span")',
    "citation_envelope.py span validation"
)

# 4 & 5. Viewer Upgrades (Compare + Changes)
V = "scripts/build_viewer.py"

# 4a. Add Compare checkbox to list items
patch(V,
    '''        '<div class="company-meta"><span>' + esc(d.muni || '-') + (d.industry ? ' &middot; ' + esc(d.industry) : '') + '</span>' +
                    '<span class="claim-badge">' + comp.count + '/5</span></div></div>';''',
    '''        '<div class="company-meta"><span>' + esc(d.muni || '-') + (d.industry ? ' &middot; ' + esc(d.industry) : '') + '</span>' +
                    '<div style="display:flex;align-items:center;gap:8px"><span class="claim-badge">' + comp.count + '/5</span>' +
                    '<input type="checkbox" class="cmp-chk" data-org="' + esc(d.org) + '" onclick="event.stopPropagation(); toggleCompare(this)"></div></div></div>';''',
    "viewer compare checkbox"
)

# 4b. Add Compare button to topbar
patch(V,
    '''<button class="theme-btn" onclick="toggleTheme()">Theme</button>''',
    '''<div style="display:flex;gap:8px"><button id="cmp-btn" class="theme-btn" style="display:none;background:var(--accent);color:white;border:none;" onclick="renderCompare()">Compare</button><button class="theme-btn" onclick="toggleTheme()">Theme</button></div>''',
    "viewer compare button"
)

# 4c. Add Recent Changes Tab to HTML
patch(V,
    '''<div class="tab" onclick="switchTab(event, \\'lo\\')">Locations</div></div>''',
    '''<div class="tab" onclick="switchTab(event, \\'lo\\')">Locations</div><div class="tab" onclick="switchTab(event, \\'ch\\')">Changes</div></div>''',
    "viewer changes tab"
)

# 4d. Add Recent Changes Content to renderCenter
patch(V,
    '''                '<div id="tc-lo" class="tab-content"><table><thead><tr><th>Workplace</th><th>Municipality</th></tr></thead><tbody>' + (locRows || '<tr><td colspan="2" style="color:var(--text-muted)">No registered subunits.</td></tr>') + '</tbody></table></div>';''',
    '''                '<div id="tc-lo" class="tab-content"><table><thead><tr><th>Workplace</th><th>Municipality</th></tr></thead><tbody>' + (locRows || '<tr><td colspan="2" style="color:var(--text-muted)">No registered subunits.</td></tr>') + '</tbody></table></div>' +
                '<div id="tc-ch" class="tab-content"><h3 style="font-family:var(--font-serif);font-size:20px;margin-bottom:12px">Recent Changes</h3><table><thead><tr><th>Field</th><th>Old Value</th><th>New Value</th><th>Type</th></tr></thead><tbody>' + 
                (d.changes && d.changes.length ? d.changes.map(ch => '<tr><td style="font-weight:600">' + esc(ch.field) + '</td><td style="color:var(--text-muted)">' + esc(ch.old_value) + '</td><td style="color:var(--green)">' + esc(ch.new_value) + '</td><td><span class="claim-badge">' + esc(ch.change_type) + '</span></td></tr>').join('') : '<tr><td colspan="4" style="color:var(--text-muted)">No changes detected.</td></tr>') + '</tbody></table></div>';''',
    "viewer changes content"
)

# 4e. Add Compare Logic JS
patch(V,
    '''        function selectCompany(org) {''',
    '''        let compareList = [];
        function toggleCompare(el) {
            const org = el.dataset.org;
            if (el.checked) { if (!compareList.includes(org)) compareList.push(org); }
            else { compareList = compareList.filter(o => o !== org); }
            document.getElementById('cmp-btn').style.display = compareList.length >= 2 ? 'block' : 'none';
        }
        function renderCompare() {
            if (compareList.length < 2) return;
            const comps = compareList.map(org => DATA.find(d => d.org === org)).filter(Boolean);
            const allFields = new Set();
            comps.forEach(d => (d.claims || []).forEach(c => { if (c.field) allFields.add(c.field); }));
            const fields = Array.from(allFields).sort();
            let html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px"><h1 style="font-family:var(--font-serif);font-size:32px;">Compare Companies</h1><button class="theme-btn" onclick="selectCompany(selectedOrg)">Close Compare</button></div>';
            html += '<table style="width:100%;border-collapse:collapse;font-size:13px;"><thead><tr><th style="text-align:left;padding:12px;border-bottom:1px solid var(--border);">Field</th>';
            comps.forEach(d => html += '<th style="text-align:left;padding:12px;border-bottom:1px solid var(--border);">' + esc(d.name) + '</th>');
            html += '</tr></thead><tbody>';
            fields.forEach(f => {
                const vals = comps.map(d => { const c = (d.claims || []).find(x => x.field === f && x.availability === 'available'); return c ? JSON.stringify(c.value) : null; });
                const diff = new Set(vals).size > 1;
                html += '<tr style="' + (diff ? 'background:var(--accent-light);' : '') + '"><td style="padding:12px;border-bottom:1px solid var(--border);font-family:monospace;">' + esc(f) + '</td>';
                vals.forEach(v => html += '<td style="padding:12px;border-bottom:1px solid var(--border);">' + (v ? esc(v.substring(0, 100)) : '-') + '</td>');
                html += '</tr>';
            });
            html += '</tbody></table>';
            document.getElementById("center").innerHTML = html;
        }
        function selectCompany(org) {''',
    "viewer compare logic"
)

print("All patches applied successfully.")