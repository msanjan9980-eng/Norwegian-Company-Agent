import json, argparse
from pathlib import Path

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Signalpost - Company Research</title>
    <style>
        :root { --bg: #f7f5f0; --surface: #ffffff; --text-main: #16161a; --text-muted: #6b6b73; --border: #e2ded5; --accent: #7d2432; --accent-light: #f4e8ea; --green: #1e8e3e; --green-light: #e6f4ea; --font-ui: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; --font-serif: Georgia, Cambria, "Times New Roman", Times, serif; --radius: 8px; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: var(--bg); color: var(--text-main); font-family: var(--font-ui); font-size: 14px; line-height: 1.5; height: 100vh; overflow: hidden; display: flex; flex-direction: column; }
        .topbar { height: 64px; border-bottom: 1px solid var(--border); background: var(--surface); display: flex; align-items: center; justify-content: space-between; padding: 0 24px; flex-shrink: 0; }
        .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-family: var(--font-serif); font-size: 22px; color: var(--text-main); }
        .brand svg { width: 24px; height: 24px; color: var(--accent); }
        .search-box { position: relative; width: 450px; }
        .search-box input { width: 100%; padding: 10px 16px 10px 40px; border: 1px solid var(--border); border-radius: 99px; background: var(--bg); color: var(--text-main); font-size: 13px; outline: none; transition: all 0.2s; }
        .search-box input:focus { border-color: var(--accent); background: var(--surface); box-shadow: 0 0 0 3px var(--accent-light); }
        .search-box svg { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; color: var(--text-muted); }
        .layout { display: flex; flex: 1; overflow: hidden; }
        .left-panel { width: 320px; border-right: 1px solid var(--border); background: var(--surface); display: flex; flex-direction: column; flex-shrink: 0; }
        .panel-header { padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .panel-title { font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); }
        .panel-count { font-size: 12px; font-weight: 600; background: var(--bg); padding: 2px 10px; border-radius: 99px; border: 1px solid var(--border); }
        .company-list { flex: 1; overflow-y: auto; }
        .company-item { padding: 16px 24px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.2s; border-left: 3px solid transparent; }
        .company-item:hover { background: var(--bg); }
        .company-item.active { background: var(--bg); border-left-color: var(--accent); }
        .company-name { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
        .company-meta { font-size: 12px; color: var(--text-muted); display: flex; justify-content: space-between; }
        .claim-badge { color: var(--accent); font-weight: 600; background: var(--accent-light); padding: 2px 8px; border-radius: 4px; }
        .center-panel { flex: 1; overflow-y: auto; padding: 40px 56px; }
        .empty-state { height: 100%; display: flex; align-items: center; justify-content: center; color: var(--text-muted); font-family: var(--font-serif); font-size: 24px; }
        .company-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 32px; }
        .header-left h1 { font-family: var(--font-serif); font-size: 42px; font-weight: 500; letter-spacing: -0.02em; line-height: 1.1; margin-bottom: 12px; }
        .company-tags { display: flex; gap: 8px; flex-wrap: wrap; }
        .tag { font-size: 12px; padding: 4px 12px; border-radius: 99px; border: 1px solid var(--border); background: var(--surface); font-weight: 500; }
        .tag.green { background: var(--green-light); border-color: transparent; color: var(--green); }
        .completeness { text-align: right; }
        .completeness-text { font-size: 13px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px; }
        .completeness-text span { color: var(--green); }
        .completeness-bar { display: flex; gap: 4px; justify-content: flex-end; }
        .dot { width: 24px; height: 6px; border-radius: 99px; background: var(--border); }
        .dot.filled { background: var(--green); }
        .bento-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; margin-bottom: 32px; }
        .bento-card { background: var(--surface); padding: 24px; display: flex; flex-direction: column; justify-content: center; }
        .bento-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 8px; }
        .bento-value { font-family: var(--font-serif); font-size: 32px; font-weight: 500; letter-spacing: -0.02em; }
        .bento-sub { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
        .tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 24px; gap: 24px; }
        .tab { padding: 16px 0; font-size: 14px; font-weight: 600; color: var(--text-muted); border-bottom: 2px solid transparent; cursor: pointer; transition: all 0.2s; }
        .tab:hover { color: var(--text-main); }
        .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
        .tab-content { display: none; animation: fadeIn 0.3s ease-out; }
        .tab-content.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th { text-align: left; padding: 12px 16px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; }
        td { padding: 12px 16px; border-bottom: 1px solid var(--border); }
        td:last-child, th:last-child { text-align: right; }
        .people-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
        .person-card { border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; display: flex; align-items: center; gap: 16px; background: var(--surface); }
        .avatar { width: 48px; height: 48px; border-radius: 50%; background: var(--bg); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-family: var(--font-serif); font-size: 18px; font-weight: 600; color: var(--accent); }
        .person-info h4 { font-size: 14px; font-weight: 600; margin-bottom: 2px; }
        .person-info p { font-size: 12px; color: var(--text-muted); }
        .right-panel { width: 380px; border-left: 1px solid var(--border); background: var(--surface); display: flex; flex-direction: column; overflow-y: auto; flex-shrink: 0; }
        .brief-box { padding: 32px; border-bottom: 1px solid var(--border); }
        .brief-box h3 { font-family: var(--font-serif); font-size: 22px; margin-bottom: 16px; }
        .brief-box p { font-size: 14px; line-height: 1.6; color: var(--text-main); white-space: pre-wrap; }
        .agent-box { background: #111827; color: white; padding: 24px; border-radius: var(--radius); margin: 24px 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        .agent-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
        .agent-header svg { width: 24px; height: 24px; color: #60a5fa; }
        .agent-header h3 { font-family: var(--font-serif); font-size: 20px; margin: 0; color: white; }
        .agent-box p { font-size: 13px; color: #9ca3af; margin-bottom: 16px; line-height: 1.5; }
        .agent-input { display: flex; gap: 8px; margin-bottom: 16px; }
        .agent-input input { flex: 1; padding: 10px 12px; border-radius: 6px; border: none; background: #1f2937; color: white; outline: none; font-family: var(--font-ui); }
        .agent-input button { padding: 10px 16px; border-radius: 6px; border: none; background: var(--accent); color: white; font-weight: 600; cursor: pointer; }
        .agent-quick { display: flex; gap: 8px; flex-wrap: wrap; }
        .quick-btn { padding: 6px 12px; border-radius: 99px; border: 1px solid #374151; background: transparent; color: #d1d5db; font-size: 12px; cursor: pointer; }
        .quick-btn:hover { background: #374151; color: white; }
        .agent-output { margin-top: 20px; padding-top: 20px; border-top: 1px solid #374151; font-size: 13px; line-height: 1.6; color: #e5e7eb; display: none; }
        @media (max-width: 1100px) { .right-panel { display: none; } }
        @media (max-width: 768px) { .layout { display: block; } .left-panel { width: 100%; height: 300px; } .center-panel { padding: 24px; } .bento-grid { grid-template-columns: 1fr; } h1 { font-size: 36px; } }
    </style>
</head>
<body>
    <header class="topbar">
        <div class="brand">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            Signalpost
        </div>
        <div class="search-box">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            <input type="text" id="search" placeholder="Search company, organisation number, industry or place...">
        </div>
        <div style="font-size:12px;color:var(--text-muted);font-weight:600" id="count">0 companies</div>
    </header>
    <div class="layout">
        <aside class="left-panel">
            <div class="panel-header">
                <div class="panel-title">Company Directory</div>
                <div class="panel-count" id="panel-count">0</div>
            </div>
            <div class="company-list" id="list"></div>
        </aside>
        <main class="center-panel" id="center">
            <div class="empty-state">Select a company</div>
        </main>
        <aside class="right-panel">
            <div class="brief-box" id="brief-box" style="display:none;">
                <h3>Company Brief</h3>
                <p id="brief-text"></p>
            </div>
            <div class="agent-box">
                <div class="agent-header">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                    <h3>Ask Signalpost</h3>
                </div>
                <p>Ask what the company does, who runs it, where it operates, or how it's doing.</p>
                <div class="agent-input">
                    <input type="text" id="agent-q" placeholder="How is this company doing?">
                    <button onclick="askAgent()">Check</button>
                </div>
                <div class="agent-quick">
                    <button class="quick-btn" onclick="setQ('Latest financials')">Latest financials</button>
                    <button class="quick-btn" onclick="setQ('Who runs it?')">Who runs it?</button>
                    <button class="quick-btn" onclick="setQ('Where are the offices?')">Locations</button>
                </div>
                <div class="agent-output" id="agent-out"></div>
            </div>
        </aside>
    </div>
    <script>
        const DATA = __DATA__;
        let selectedOrg = null;
        let currentCompany = null;

        function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
        function fmtCurr(n) { if (n == null || n === '') return '-'; const v = Number(n); if (isNaN(v)) return esc(n); if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(1) + 'B NOK'; if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1) + 'M NOK'; if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(0) + 'K NOK'; return v.toLocaleString() + ' NOK'; }

        function getVal(claims, f) {
            const c = claims.find(x => x.field === f && x.availability === 'available');
            return c ? c.value : null;
        }

        function calcCompleteness(claims) {
            const hasId = true;
            const hasFin = claims.some(c => c.field.startsWith('financials.') && c.availability === 'available');
            const hasPpl = claims.some(c => c.field.startsWith('people.role') && c.availability === 'available');
            const hasLoc = claims.some(c => c.field.startsWith('locations.subunit') && c.availability === 'available');
            const hasAct = claims.some(c => c.field.startsWith('activity') && c.availability === 'available');
            return [hasId, hasFin, hasPpl, hasLoc, hasAct];
        }

        function renderList(rows) {
            document.getElementById("panel-count").textContent = rows.length;
            document.getElementById("count").textContent = rows.length + " companies";
            const list = document.getElementById("list");
            if (!rows.length) { list.innerHTML = '<div style="padding:20px;color:var(--text-muted);text-align:center">No companies found.</div>'; return; }
            list.innerHTML = rows.map(d => {
                const areas = calcCompleteness(d.claims).filter(Boolean).length;
                return '<div class="company-item ' + (d.org === selectedOrg ? 'active' : '') + '" onclick="selectCompany(\'' + esc(d.org) + '\')">' +
                    '<div class="company-name">' + esc(d.name || 'Unknown') + '</div>' +
                    '<div class="company-meta"><span>' + esc(d.muni || '-') + (d.industry ? ' &middot; ' + esc(d.industry) : '') + '</span>' +
                    '<span class="claim-badge">' + areas + '/5 data</span></div></div>';
            }).join("");
        }

        function selectCompany(org) {
            selectedOrg = org;
            const d = DATA.find(x => x.org === org);
            if (!d) return;
            currentCompany = d;
            const q = document.getElementById("search").value.toLowerCase();
            renderList(DATA.filter(x => !q || esc(x.name).toLowerCase().includes(q) || esc(x.org).includes(q) || esc(x.muni || '').toLowerCase().includes(q)));
            renderCenter(d);
            renderRight(d);
            document.getElementById("agent-out").style.display = "none";
        }

        function renderCenter(d) {
            const claims = d.claims || [];
            const rev = getVal(claims, 'financials.revenue');
            const op = getVal(claims, 'financials.operating_result');
            const emp = getVal(claims, 'identity.employees');
            const locCount = claims.filter(c => c.field === 'locations.subunit.name').length;
            const pplCount = claims.filter(c => c.field.startsWith('people.role')).length;
            const grpCount = claims.filter(c => c.field.startsWith('group.child')).length;
            
            const areas = calcCompleteness(claims);
            const completeness = areas.filter(Boolean).length;
            const dots = areas.map(a => '<div class="dot ' + (a ? 'filled' : '') + '"></div>').join('');

            const finRows = claims.filter(c => c.field.startsWith('financials.')).map(c => {
                const v = (typeof c.value === 'object' && c.value !== null) ? c.value : { amount: c.value };
                return '<tr><td style="font-weight:600">' + esc(c.field.split('.').slice(1).join(' ').toUpperCase()) + '</td><td style="color:var(--text-muted)">' + esc(v.year || '-') + '</td><td style="font-family:monospace">' + fmtCurr(v.amount) + '</td></tr>';
            }).join('');

            const pplCards = claims.filter(c => c.field.startsWith('people.role') && c.value && c.value.name).map(c => {
                const nameStr = esc(c.value.name);
                const initials = nameStr.split(' ').map(n => n[0] || '').join('').slice(0, 2).toUpperCase();
                return '<div class="person-card"><div class="avatar">' + initials + '</div><div class="person-info"><h4>' + nameStr + '</h4><p>' + esc(c.value.role || c.field.split('.').slice(2).join(' ')) + '</p></div></div>';
            }).join('');

            const locRows = claims.filter(c => c.field === 'locations.subunit.name').map(c => {
                const v = c.value || {};
                const m = claims.find(x => x.field === 'locations.subunit.municipality' && (x.value || {}).subunit_orgnr === v.subunit_orgnr);
                return '<tr><td style="font-weight:600">' + esc(v.name || v.subunit_orgnr) + '</td><td style="color:var(--text-muted)">' + esc((m && m.value || {}).municipality || '-') + '</td></tr>';
            }).join('');

            document.getElementById("center").innerHTML = 
                '<div class="company-header"><div class="header-left"><h1>' + esc(d.name) + '</h1>' +
                '<div class="company-tags"><span class="tag">' + esc(d.org) + ' &middot; ' + esc(d.form) + (d.muni ? ' &middot; ' + esc(d.muni) : '') + '</span>' +
                (rev ? '<span class="tag green">Latest filing</span>' : '') +
                (getVal(claims, 'official_website') ? '<a href="' + esc(getVal(claims, 'official_website')) + '" target="_blank" class="tag green">Website &nearr;</a>' : '') +
                '</div></div><div class="completeness"><div class="completeness-text"><span>' + completeness + '</span> of 5 areas</div><div class="completeness-bar">' + dots + '</div></div></div>' +
                
                '<div class="bento-grid">' +
                '<div class="bento-card"><div class="bento-label">Revenue</div><div class="bento-value">' + fmtCurr(rev && rev.amount) + '</div><div class="bento-sub">' + (rev && rev.year ? 'FY ' + rev.year : 'N/A') + '</div></div>' +
                '<div class="bento-card"><div class="bento-label">Operating Result</div><div class="bento-value" style="color:' + (op && op.amount < 0 ? 'var(--accent)' : 'inherit') + '">' + fmtCurr(op && op.amount) + '</div><div class="bento-sub">' + (op && op.year ? 'FY ' + op.year : 'N/A') + '</div></div>' +
                '<div class="bento-card"><div class="bento-label">Employees</div><div class="bento-value">' + (emp != null ? esc(emp) : '-') + '</div><div class="bento-sub">' + (emp != null ? 'Official record' : 'Not reported') + '</div></div>' +
                '<div class="bento-card"><div class="bento-label">Workplaces</div><div class="bento-value">' + locCount + '</div><div class="bento-sub">Subunits</div></div>' +
                '<div class="bento-card"><div class="bento-label">Key People</div><div class="bento-value">' + pplCount + '</div><div class="bento-sub">Role records</div></div>' +
                '<div class="bento-card"><div class="bento-label">Group Entities</div><div class="bento-value">' + grpCount + '</div><div class="bento-sub">Children</div></div>' +
                '</div>' +

                '<div class="tabs"><div class="tab active" onclick="switchTab(event, \'ov\')">Overview</div><div class="tab" onclick="switchTab(event, \'fi\')">Financials</div><div class="tab" onclick="switchTab(event, \'pe\')">Leadership</div><div class="tab" onclick="switchTab(event, \'lo\')">Locations</div></div>' +
                
                '<div id="tc-ov" class="tab-content active"><h3 style="font-family:var(--font-serif);font-size:20px;margin-bottom:12px">Overview</h3><p style="color:var(--text-muted);line-height:1.7;max-width:800px;white-space:pre-wrap">' + esc(d.summary || 'No summary available.') + '</p></div>' +
                '<div id="tc-fi" class="tab-content"><table><thead><tr><th>Metric</th><th>Year</th><th>Value</th></tr></thead><tbody>' + (finRows || '<tr><td colspan="3" style="color:var(--text-muted)">No financial data.</td></tr>') + '</tbody></table></div>' +
                '<div id="tc-pe" class="tab-content"><div class="people-list">' + (pplCards || '<p style="color:var(--text-muted)">No public role records.</p>') + '</div></div>' +
                '<div id="tc-lo" class="tab-content"><table><thead><tr><th>Workplace</th><th>Municipality</th></tr></thead><tbody>' + (locRows || '<tr><td colspan="2" style="color:var(--text-muted)">No registered subunits.</td></tr>') + '</tbody></table></div>';
        }

        function renderRight(d) {
            document.getElementById("brief-box").style.display = "block";
            document.getElementById("brief-text").textContent = d.summary || "No summary available.";
        }

        function switchTab(ev, id) {
            document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
            ev.target.classList.add("active");
            document.getElementById("tc-" + id).classList.add("active");
        }

        function setQ(text) {
            document.getElementById("agent-q").value = text;
            askAgent();
        }

        function askAgent() {
            if (!currentCompany) return;
            const q = document.getElementById("agent-q").value.toLowerCase().trim();
            const out = document.getElementById("agent-out");
            if (!q) return;
            out.style.display = "block";
            out.innerHTML = "Analyzing evidence...";
            
            const d = currentCompany;
            const claims = d.claims || [];
            
            setTimeout(() => {
                let res = "No verified match for that question.";
                if (q.includes("financial") || q.includes("revenue") || q.includes("money") || q.includes("result")) {
                    const rev = getVal(claims, 'financials.revenue');
                    const op = getVal(claims, 'financials.operating_result');
                    if (rev && rev.amount) {
                        res = "<strong>Financials for " + esc(d.name) + ":</strong><br>Latest reported revenue: <strong>" + fmtCurr(rev.amount) + "</strong> (FY " + rev.year + ").<br>Operating result: <strong>" + fmtCurr(op && op.amount) + "</strong>.";
                    } else {
                        res = "No financial records were found in the register for this company.";
                    }
                } else if (q.includes("who") || q.includes("lead") || q.includes("run") || q.includes("ceo") || q.includes("board")) {
                    const people = claims.filter(c => c.field.startsWith('people.role') && c.value && c.value.name);
                    if (people.length) {
                        res = "<strong>Key people:</strong><br>" + people.slice(0, 3).map(p => esc(p.value.name) + " (" + esc(p.value.role || 'Role') + ")").join('<br>');
                    } else {
                        res = "No public role records were found for this company.";
                    }
                } else if (q.includes("where") || q.includes("office") || q.includes("location") || q.includes("address")) {
                    const locs = claims.filter(c => c.field === 'locations.subunit.name' && c.value && c.value.name);
                    if (locs.length) {
                        res = "<strong>Registered workplaces:</strong><br>" + locs.slice(0, 5).map(l => "&bull; " + esc(l.value.name)).join('<br>');
                    } else {
                        res = "The registered business address is in " + esc(d.muni || "an unknown municipality") + ". No separate subunits were found.";
                    }
                } else if (q.includes("what") || q.includes("do") || q.includes("about") || q.includes("brief")) {
                    res = "<strong>Overview:</strong><br>" + esc(d.summary || 'No summary available.');
                }
                out.innerHTML = res;
            }, 400);
        }

        document.getElementById("search").addEventListener("input", e => {
            const q = e.target.value.toLowerCase();
            renderList(DATA.filter(x => !q || esc(x.name).toLowerCase().includes(q) || esc(x.org).includes(q) || esc(x.muni || '').toLowerCase().includes(q)));
        });

        renderList(DATA);
        if (DATA.length > 0) selectCompany(DATA[0].org);
    </script>
</body>
</html>"""

def _safe(v):
    if v is None: return ""
    if isinstance(v, list): return ", ".join(str(x) for x in v if x)
    if isinstance(v, dict): return json.dumps(v, ensure_ascii=False)
    return str(v)

def _claim_val(claims, field):
    for c in claims:
        if c.get("field") == field and c.get("availability") == "available":
            return c.get("value")
    return None

def _row(env):
    claims = env.get("claims") or []
    addr = _claim_val(claims, "identity.business_address") or {}
    ind = _claim_val(claims, "identity.industry") or {}
    return {
        "org": _safe(env.get("organisation_number")),
        "name": _safe(_claim_val(claims, "identity.name") or _claim_val(claims, "identity.navn")),
        "form": _safe(_claim_val(claims, "identity.legal_form")),
        "muni": _safe(addr.get("kommune")) if isinstance(addr, dict) else "",
        "industry": _safe(ind.get("beskrivelse")) if isinstance(ind, dict) else "",
        "summary": _safe(env.get("summary")),
        "claims": [
            {"field": _safe(c.get("field")), "value": c.get("value"), "availability": _safe(c.get("availability"))}
            for c in claims
        ],
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--envelopes", required=True)
    ap.add_argument("--out", default=".")
    args = ap.parse_args()
    rows = [_row(json.loads(l)) for l in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "index.html"
    target.write_text(HTML.replace("__DATA__", json.dumps(rows, ensure_ascii=False, default=str)), encoding="utf-8")
    print(f"Wrote {target} with {len(rows)} companies")

if __name__ == "__main__":
    main()