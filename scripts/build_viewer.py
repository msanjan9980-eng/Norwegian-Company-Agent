import json, argparse
from pathlib import Path

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Signalpost - Company Research</title>
    <style>
        :root { 
            --bg: #f8f7f3; --surface: #ffffff; --text-main: #1a1a1f; --text-muted: #6b6b73; --border: #e6e3db; 
            --accent: #7d2432; --accent-light: #f4e8ea; --green: #1e8e3e; --green-light: #e6f4ea; 
            --font-ui: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
            --font-serif: Georgia, Cambria, "Times New Roman", Times, serif; --radius: 10px; 
        }
        [data-theme="dark"] {
            --bg: #0f1115; --surface: #171a21; --text-main: #e6e6e6; --text-muted: #9aa0a6; --border: #252a34;
            --accent: #e05a6c; --accent-light: #2c1317; --green: #34d399; --green-light: #064e3b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: var(--bg); color: var(--text-main); font-family: var(--font-ui); font-size: 14px; line-height: 1.5; height: 100vh; overflow: hidden; display: flex; flex-direction: column; transition: background 0.3s, color 0.3s; }
        
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #d1cdc5; border-radius: 99px; }
        [data-theme="dark"] ::-webkit-scrollbar-thumb { background: #374151; }

        /* Topbar */
        .topbar { height: 64px; border-bottom: 1px solid var(--border); background: var(--surface); display: flex; align-items: center; justify-content: space-between; padding: 0 24px; flex-shrink: 0; z-index: 10; transition: background 0.3s; }
        .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-family: var(--font-serif); font-size: 22px; color: var(--text-main); }
        .brand svg { width: 24px; height: 24px; color: var(--accent); }
        .search-box { position: relative; width: 400px; }
        .search-box input { width: 100%; padding: 10px 16px 10px 40px; border: 1px solid var(--border); border-radius: 99px; background: var(--bg); color: var(--text-main); font-size: 13px; outline: none; transition: all 0.2s; }
        .search-box input:focus { border-color: var(--accent); background: var(--surface); box-shadow: 0 0 0 3px var(--accent-light); }
        .search-box svg { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; color: var(--text-muted); }
        .theme-btn { background: var(--bg); border: 1px solid var(--border); color: var(--text-main); padding: 8px 12px; border-radius: var(--radius); cursor: pointer; font-weight: 600; font-size: 12px; transition: all 0.2s; }
        .theme-btn:hover { background: var(--surface); }
        
        /* Layout */
        .layout { display: flex; flex: 1; overflow: hidden; }
        
        /* Left Panel */
        .left-panel { width: 320px; border-right: 1px solid var(--border); background: var(--surface); display: flex; flex-direction: column; flex-shrink: 0; transition: background 0.3s; }
        .panel-header { padding: 20px 24px 16px; border-bottom: 1px solid var(--border); }
        .panel-title-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .panel-title { font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); }
        .panel-count { font-size: 12px; font-weight: 600; background: var(--bg); padding: 2px 10px; border-radius: 99px; border: 1px solid var(--border); }
        .sort-row { display: flex; gap: 8px; }
        .sort-btn { flex: 1; padding: 6px; border: 1px solid var(--border); background: var(--bg); border-radius: 6px; font-size: 11px; font-weight: 600; color: var(--text-muted); cursor: pointer; text-align: center; transition: all 0.2s; }
        .sort-btn.active { background: var(--accent-light); border-color: var(--accent); color: var(--accent); }
        
        .company-list { flex: 1; overflow-y: auto; }
        .company-item { padding: 16px 24px; border-bottom: 1px solid var(--border); cursor: pointer; transition: all 0.2s; border-left: 3px solid transparent; }
        .company-item:hover { background: var(--bg); }
        .company-item.active { background: var(--bg); border-left-color: var(--accent); }
        .company-name { font-weight: 600; font-size: 14px; margin-bottom: 4px; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .company-meta { font-size: 12px; color: var(--text-muted); display: flex; justify-content: space-between; align-items: center; gap: 8px; }
        .company-meta span:first-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 170px; display: inline-block; }
        .claim-badge { color: var(--accent); font-weight: 600; background: var(--accent-light); padding: 2px 8px; border-radius: 4px; font-size: 11px; flex-shrink: 0; }
        
        /* Center Panel */
        .center-panel { flex: 1; overflow-y: auto; padding: 40px 48px; }
        .company-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 32px; }
        .header-left h1 { font-family: var(--font-serif); font-size: 38px; font-weight: 500; letter-spacing: -0.02em; line-height: 1.1; margin-bottom: 12px; }
        .company-tags { display: flex; gap: 8px; flex-wrap: wrap; }
        .tag { font-size: 12px; padding: 4px 12px; border-radius: 99px; border: 1px solid var(--border); background: var(--surface); font-weight: 500; display: inline-flex; align-items: center; gap: 6px; transition: background 0.3s; }
        .tag.green { background: var(--green-light); border-color: transparent; color: var(--green); }
        .tag.green .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); }
        
        /* Completeness Circle */
        .comp-circle { width: 64px; height: 64px; border-radius: 50%; background: conic-gradient(var(--green) 0%, var(--green) calc(var(--pct) * 1%), var(--border) calc(var(--pct) * 1%), var(--border) 100%); display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); flex-shrink: 0; }
        .comp-inner { width: 52px; height: 52px; border-radius: 50%; background: var(--surface); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 15px; color: var(--text-main); transition: background 0.3s; }
        
        /* Bento Grid */
        .bento-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; margin-bottom: 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.03); }
        .bento-card { background: var(--surface); padding: 24px; display: flex; flex-direction: column; justify-content: center; transition: background 0.2s; }
        .bento-card:hover { background: var(--bg); }
        .bento-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 8px; }
        .bento-value { font-family: var(--font-serif); font-size: 28px; font-weight: 500; letter-spacing: -0.02em; }
        .bento-sub { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
        
        /* Tabs */
        .tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 24px; gap: 24px; }
        .tab { padding: 16px 0; font-size: 14px; font-weight: 600; color: var(--text-muted); border-bottom: 2px solid transparent; cursor: pointer; transition: all 0.2s; }
        .tab:hover { color: var(--text-main); }
        .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
        .tab-content { display: none; animation: fadeIn 0.3s ease-out; }
        .tab-content.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        
        /* Tables */
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th { text-align: left; padding: 12px 16px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; }
        td { padding: 12px 16px; border-bottom: 1px solid var(--border); }
        td:last-child, th:last-child { text-align: right; }
        
        /* Bar Chart */
        .chart-container { display: flex; align-items: flex-end; gap: 16px; height: 140px; padding-top: 20px; margin-bottom: 24px; border-bottom: 1px solid var(--border); }
        .chart-bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
        .chart-bar { width: 100%; max-width: 40px; background: var(--accent); border-radius: 4px 4px 0 0; transition: height 0.5s ease-out; position: relative; }
        .chart-bar:hover { opacity: 0.8; }
        .chart-label { font-size: 11px; color: var(--text-muted); margin-top: 8px; }
        
        /* People */
        .people-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
        .person-card { border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; display: flex; align-items: center; gap: 16px; background: var(--surface); box-shadow: 0 2px 6px rgba(0,0,0,0.02); transition: background 0.3s; }
        .avatar { width: 48px; height: 48px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), #b56576); color: white; display: flex; align-items: center; justify-content: center; font-family: var(--font-serif); font-size: 18px; font-weight: 600; flex-shrink: 0; }
        .person-info h4 { font-size: 14px; font-weight: 600; margin-bottom: 2px; }
        .person-info p { font-size: 12px; color: var(--text-muted); }
        
        /* Right Panel */
        .right-panel { width: 380px; border-left: 1px solid var(--border); background: var(--surface); display: flex; flex-direction: column; flex-shrink: 0; height: 100%; transition: background 0.3s; }
        .brief-box { padding: 32px; flex: 1; overflow-y: auto; }
        .brief-box h3 { font-family: var(--font-serif); font-size: 22px; margin-bottom: 16px; }
        .brief-box p { font-size: 14px; line-height: 1.6; color: var(--text-main); white-space: pre-wrap; }
        
        /* Agent Chat */
        .agent-box { background: #111827; color: white; padding: 20px; border-radius: var(--radius); margin: 0 24px 24px 24px; flex-shrink: 0; box-shadow: 0 8px 24px rgba(0,0,0,0.15); display: flex; flex-direction: column; max-height: 400px; border: 1px solid rgba(255,255,255,0.05); }
        .agent-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
        .agent-header svg { width: 20px; height: 20px; color: #60a5fa; }
        .agent-header h3 { font-family: var(--font-serif); font-size: 18px; margin: 0; color: white; }
        .chat-window { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; min-height: 80px; }
        .chat-window::-webkit-scrollbar { width: 4px; }
        .chat-window::-webkit-scrollbar-thumb { background: #374151; }
        .chat-bubble { padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.5; max-width: 90%; animation: popIn 0.2s ease-out; }
        @keyframes popIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }
        .chat-bubble.user { background: #374151; color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
        .chat-bubble.agent { background: #1f2937; color: #e5e7eb; align-self: flex-start; border-bottom-left-radius: 2px; }
        .agent-input { display: flex; gap: 8px; }
        .agent-input input { flex: 1; padding: 10px 14px; border-radius: 8px; border: none; background: #1f2937; color: white; outline: none; font-family: var(--font-ui); font-size: 13px; }
        .agent-input input:focus { box-shadow: 0 0 0 2px #3b82f6; }
        .agent-input button { padding: 0 16px; border-radius: 8px; border: none; background: var(--accent); color: white; font-weight: 600; cursor: pointer; transition: background 0.2s; }
        .agent-input button:hover { background: #9a2e3f; }
        .typing { display: inline-block; font-style: italic; color: #9ca3af; font-size: 12px; }
        
        @media (max-width: 1100px) { .right-panel { display: none; } }
        @media (max-width: 768px) {
            .topbar { padding: 0 12px; gap: 8px; }
            .mobile-menu-btn { display: block !important; }
            .brand span { display: none; }
            .search-box { display: none; }
            .layout { display: block; position: relative; overflow: hidden; }
            .left-panel { position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 50; border-right: none; transform: translateX(-100%); transition: transform 0.3s ease; }
            .left-panel.open { transform: translateX(0); }
            .center-panel { width: 100%; height: 100%; padding: 20px; overflow-y: auto; }
            .bento-grid { grid-template-columns: 1fr; }
            h1 { font-size: 32px; }
            .company-header { flex-direction: column; gap: 16px; }
            .comp-circle { align-self: flex-start; }
            .company-tags { flex-wrap: wrap; }
        }
    </style>
</head>
<body>
    <header class="topbar">
        <button class="mobile-menu-btn" onclick="toggleMenu()" style="display:none; background:none; border:none; color:var(--text-main); padding:8px; cursor:pointer;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px;"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
        </button>
        <div class="brand">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            <span>Signalpost</span>
        </div>
        <div class="search-box">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            <input type="text" id="search" placeholder="Search company, organisation number, industry or place...">
        </div>
        <div style="display:flex;gap:8px"><button id="cmp-btn" class="theme-btn" style="display:none;background:var(--accent);color:white;border:none;" onclick="renderCompare()">Compare</button><button class="theme-btn" onclick="toggleTheme()">Theme</button></div>
    </header>
    <div class="layout">
        <aside class="left-panel">
            <div class="panel-header">
                <div class="panel-title-row">
                    <div class="panel-title">Company Directory</div>
                    <div class="panel-count" id="panel-count">0</div>
                </div>
                <div class="sort-row">
                    <div class="sort-btn active" onclick="setSort('name')">Name</div>
                    <div class="sort-btn" onclick="setSort('revenue')">Revenue</div>
                </div>
            </div>
            <div class="company-list" id="list"></div>
        </aside>
        <main class="center-panel" id="center"></main>
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
                <div class="chat-window" id="chat-window"></div>
                <div class="agent-input">
                    <input type="text" id="agent-q" placeholder="Ask a question..." onkeypress="if(event.key === 'Enter') askAgent()">
                    <button onclick="askAgent()">Send</button>
                </div>
            </div>
        </aside>
    </div>
    <script>
        window.onerror = function(msg, url, line, col, error) {
            document.body.innerHTML = '<div style="padding:20px;color:red;font-family:monospace;white-space:pre-wrap">JS ERROR: ' + msg + '\nLine: ' + line + '\n' + (error ? error.stack : '') + '</div>';
        };
        const DATA = __DATA__;
        let selectedOrg = null;
        let currentCompany = null;
        let currentSort = 'name';

        function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
        function fmtCurr(n) { if (n == null || n === '') return '-'; const v = Number(n); if (isNaN(v)) return esc(n); if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(1) + 'B NOK'; if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1) + 'M NOK'; if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(0) + 'K NOK'; return v.toLocaleString() + ' NOK'; }

        function getVal(claims, f) {
            const c = claims.find(x => x.field === f && x.availability === 'available');
            return c ? c.value : null;
        }

        function calcCompleteness(claims) {
            const areas = [true,
                claims.some(c => c.field.startsWith('financials.') && c.availability === 'available'),
                claims.some(c => c.field.startsWith('people.role') && c.availability === 'available'),
                claims.some(c => c.field.startsWith('locations.subunit') && c.availability === 'available'),
                claims.some(c => c.field.startsWith('activity') && c.availability === 'available')
            ];
            return { count: areas.filter(Boolean).length, pct: (areas.filter(Boolean).length / 5) * 100 };
        }

        function renderList() {
            let rows = DATA.filter(d => {
                const q = document.getElementById("search").value.toLowerCase();
                return !q || esc(d.name).toLowerCase().includes(q) || esc(d.org).includes(q) || esc(d.muni || '').toLowerCase().includes(q);
            });

            if (currentSort === 'name') {
                rows.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
            } else {
                rows.sort((a, b) => {
                    const va = a.rev && a.rev.amount ? a.rev.amount : 0;
                    const vb = b.rev && b.rev.amount ? b.rev.amount : 0;
                    return vb - va;
                });
            }

            document.getElementById("panel-count").textContent = rows.length;
            
            const list = document.getElementById("list");
            if (!rows.length) { list.innerHTML = '<div style="padding:20px;color:var(--text-muted);text-align:center">No companies found.</div>'; return; }
            
            list.innerHTML = rows.map(d => {
                const comp = calcCompleteness(d.claims);
                return '<div class="company-item ' + (d.org === selectedOrg ? 'active' : '') + '" onclick="selectCompany(\'' + esc(d.org) + '\')">' +
                    '<div class="company-name">' + esc(d.name || 'Unknown') + '</div>' +
                    '<div class="company-meta"><span>' + esc(d.muni || '-') + (d.industry ? ' &middot; ' + esc(d.industry) : '') + '</span>' +
                    '<div style="display:flex;align-items:center;gap:8px"><span class="claim-badge">' + comp.count + '/5</span>' +
                    '<input type="checkbox" class="cmp-chk" data-org="' + esc(d.org) + '" onclick="event.stopPropagation(); toggleCompare(this)"></div></div></div>';
            }).join("");
        }

        function setSort(type) {
            currentSort = type;
            document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            renderList();
        }

        let compareList = [];
        function toggleCompare(el) {
            const org = el.dataset.org;
            if (el.checked) { if (!compareList.includes(org)) compareList.push(org); }
            else { compareList = compareList.filter(o => o !== org); }
            document.getElementById('cmp-btn').style.display = compareList.length >= 2 ? 'block' : 'none';
        }
        function renderCompare() {
            document.querySelector('.left-panel').classList.remove('open');
            if (compareList.length < 2) return;
            const comps = compareList.map(org => DATA.find(d => d.org === org)).filter(Boolean);
            const allFields = new Set();
            comps.forEach(d => (d.claims || []).forEach(c => { if (c.field) allFields.add(c.field); }));
            const fields = Array.from(allFields).sort();
            let html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px"><h1 style="font-family:var(--font-serif);font-size:32px;">Compare Companies</h1><button class="theme-btn" onclick="selectCompany(DATA[0].org)">Close Compare</button></div>';
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
        function toggleMenu() {
            document.querySelector('.left-panel').classList.toggle('open');
        }
        function selectCompany(org) {
            selectedOrg = org;
            const d = DATA.find(x => x.org === org);
            if (!d) return;
            currentCompany = d;
            document.querySelector('.left-panel').classList.remove('open');
            renderList();
            renderCenter(d);
            renderRight(d);
        }

        function renderCenter(d) {
            const claims = d.claims || [];
            const rev = getVal(claims, 'financials.revenue');
            const op = getVal(claims, 'financials.operating_result');
            const emp = getVal(claims, 'identity.employees');
            const locCount = claims.filter(c => c.field === 'locations.subunit.name').length;
            const pplCount = claims.filter(c => c.field.startsWith('people.role')).length;
            const grpCount = claims.filter(c => c.field.startsWith('group.child')).length;
            const comp = calcCompleteness(claims);

            const getNum = (val) => {
                if (typeof val === 'number') return val;
                if (!val) return 0;
                const num = parseFloat(String(val).replace(/[^0-9.-]/g, ''));
                return isNaN(num) ? 0 : num;
            };
            const finClaims = claims.filter(c => c.field.startsWith('financials.')).map(c => {
                const v = (typeof c.value === 'object' && c.value !== null) ? c.value : { amount: c.value };
                return { field: c.field.split('.').slice(1).join(' ').toUpperCase(), year: v.year || '-', amount: getNum(v.amount) };
            }).sort((a, b) => String(b.year).localeCompare(String(a.year)));
            
            const revHistory = finClaims.filter(c => c.field === 'REVENUE' && c.amount).sort((a, b) => String(a.year).localeCompare(String(b.year)));
            let chartHtml = '';
            if (revHistory.length > 0) {
                const maxVal = Math.max(...revHistory.map(r => Math.abs(r.amount))) || 1;
                chartHtml = '<div class="chart-container">' + revHistory.map(r => {
                    const h = Math.max(4, (Math.abs(r.amount) / maxVal) * 100);
                    return '<div class="chart-bar-wrap"><div class="chart-bar" style="height:' + h + '%" title="' + fmtCurr(r.amount) + '"></div><div class="chart-label">' + r.year + '</div></div>';
                }).join('') + '</div>';
            }

            const finRows = finClaims.map(c => '<tr><td style="font-weight:600">' + c.field + '</td><td style="color:var(--text-muted)">' + c.year + '</td><td style="font-family:monospace">' + fmtCurr(c.amount) + '</td></tr>').join('');

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

            const jobClaims = claims.filter(c => c.field.startsWith('jobs.'));
            const jobRows = jobClaims.map(c => {
                if (c.field === 'jobs.has_active_postings') return '<div style="font-weight:600;margin-bottom:8px;">Active Postings: ' + (c.value ? 'Yes' : 'No') + '</div>';
                if (c.field === 'jobs.posting') {
                    const v = c.value || {};
                    return '<div class="person-card" style="margin-bottom:8px;"><div class="person-info"><h4>' + esc(v.title) + '</h4><p>' + esc(v.link || '') + '</p></div></div>';
                }
                return '';
            }).join('');

            const actClaims = claims.filter(c => c.field.startsWith('activity.') || c.field.startsWith('web.activity.'));
            const actRows = actClaims.map(c => {
                const v = c.value || {};
                const date = v.date || v.year || 'Unknown date';
                return '<tr><td style="font-weight:600">' + esc(c.field) + '</td><td>' + esc(date) + '</td><td>' + esc(JSON.stringify(v)) + '</td></tr>';
            }).join('');

            document.getElementById("center").innerHTML = 
                '<div class="company-header"><div class="header-left"><h1>' + esc(d.name) + '</h1>' +
                '<div class="company-tags"><span class="tag">' + esc(d.org) + ' &middot; ' + esc(d.form) + (d.muni ? ' &middot; ' + esc(d.muni) : '') + '</span>' +
                (rev ? '<span class="tag green"><div class="dot"></div>Latest filing</span>' : '') +
                (getVal(claims, 'official_website') ? '<a href="' + esc(getVal(claims, 'official_website')) + '" target="_blank" class="tag green"><div class="dot"></div>Website</a>' : '') +
                '</div></div><div class="comp-circle" style="--pct: ' + comp.pct + '"><div class="comp-inner">' + comp.count + '/5</div></div></div>' +
                
                '<div class="bento-grid">' +
                '<div class="bento-card"><div class="bento-label">Revenue</div><div class="bento-value">' + fmtCurr(rev && rev.amount) + '</div><div class="bento-sub">' + (rev && rev.year ? 'FY ' + rev.year : 'N/A') + '</div></div>' +
                '<div class="bento-card"><div class="bento-label">Operating Result</div><div class="bento-value" style="color:' + (op && op.amount < 0 ? 'var(--accent)' : 'inherit') + '">' + fmtCurr(op && op.amount) + '</div><div class="bento-sub">' + (op && op.year ? 'FY ' + op.year : 'N/A') + '</div></div>' +
                '<div class="bento-card"><div class="bento-label">Employees</div><div class="bento-value">' + (emp != null ? esc(emp) : '-') + '</div><div class="bento-sub">' + (emp != null ? 'Official record' : 'Not reported') + '</div></div>' +
                '<div class="bento-card"><div class="bento-label">Workplaces</div><div class="bento-value">' + locCount + '</div><div class="bento-sub">Subunits</div></div>' +
                '<div class="bento-card"><div class="bento-label">Key People</div><div class="bento-value">' + pplCount + '</div><div class="bento-sub">Role records</div></div>' +
                '<div class="bento-card"><div class="bento-label">Group Entities</div><div class="bento-value">' + grpCount + '</div><div class="bento-sub">Children</div></div>' +
                '</div>' +

                '<div class="tabs"><div class="tab active" onclick="switchTab(event, \'ov\')">Overview</div><div class="tab" onclick="switchTab(event, \'fi\')">Financials</div><div class="tab" onclick="switchTab(event, \'pe\')">Leadership</div><div class="tab" onclick="switchTab(event, \'lo\')">Locations</div><div class="tab" onclick="switchTab(event, \'ch\')">Changes</div><div class="tab" onclick="switchTab(event, \'hi\')">Hiring</div><div class="tab" onclick="switchTab(event, \'ac\')">Activity</div></div>' +
                
                '<div id="tc-ov" class="tab-content active"><h3 style="font-family:var(--font-serif);font-size:20px;margin-bottom:12px">Overview</h3><p style="color:var(--text-muted);line-height:1.7;max-width:800px;white-space:pre-wrap">' + esc(d.summary || 'No summary available.') + '</p></div>' +
                '<div id="tc-fi" class="tab-content">' + (chartHtml || '<p style="padding:20px;color:var(--text-muted);text-align:center">No historical chart data available.</p>') + '<table><thead><tr><th>Metric</th><th>Year</th><th>Value</th></tr></thead><tbody>' + (finRows || '<tr><td colspan="3" style="color:var(--text-muted)">No financial data.</td></tr>') + '</tbody></table></div>' +
                '<div id="tc-pe" class="tab-content"><div class="people-list">' + (pplCards || '<p style="color:var(--text-muted)">No public role records.</p>') + '</div></div>' +
                '<div id="tc-lo" class="tab-content"><table><thead><tr><th>Workplace</th><th>Municipality</th></tr></thead><tbody>' + (locRows || '<tr><td colspan="2" style="color:var(--text-muted)">No registered subunits.</td></tr>') + '</tbody></table></div>' +
                '<div id="tc-ch" class="tab-content"><h3 style="font-family:var(--font-serif);font-size:20px;margin-bottom:12px">Recent Changes</h3><table><thead><tr><th>Field</th><th>Old Value</th><th>New Value</th><th>Type</th></tr></thead><tbody>' + 
                (d.changes && d.changes.length ? d.changes.map(ch => '<tr><td style="font-weight:600">' + esc(ch.field) + '</td><td style="color:var(--text-muted)">' + esc(ch.old_value) + '</td><td style="color:var(--green)">' + esc(ch.new_value) + '</td><td><span class="claim-badge">' + esc(ch.change_type) + '</span></td></tr>').join('') : '<tr><td colspan="4" style="color:var(--text-muted)">No changes detected.</td></tr>') + '</tbody></table></div>' +
                '<div id="tc-hi" class="tab-content"><h3 style="font-family:var(--font-serif);font-size:20px;margin-bottom:12px">Hiring</h3>' + 
                (jobRows || '<p style="color:var(--text-muted)">No active postings found in the checked sources.</p>') + '</div>' +
                '<div id="tc-ac" class="tab-content"><h3 style="font-family:var(--font-serif);font-size:20px;margin-bottom:12px">Public Activity</h3><table><thead><tr><th>Event</th><th>Date</th><th>Details</th></tr></thead><tbody>' + 
                (actRows || '<tr><td colspan="3" style="color:var(--text-muted)">No dated public activity found in the checked sources.</td></tr>') + '</tbody></table></div>';
        }

        function renderRight(d) {
            document.getElementById("brief-box").style.display = "block";
            document.getElementById("brief-text").textContent = d.summary || "No summary available.";
            const win = document.getElementById("chat-window");
            win.innerHTML = '';
            addChat('agent', 'Hi! I am the Signalpost AI. Ask me about the financials, leadership, or locations for ' + esc(d.name) + '.');
        }

        function switchTab(ev, id) {
            document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
            ev.target.classList.add("active");
            document.getElementById("tc-" + id).classList.add("active");
        }

        function addChat(role, text) {
            const win = document.getElementById("chat-window");
            const bubble = document.createElement("div");
            bubble.className = "chat-bubble " + role;
            bubble.innerHTML = text;
            win.appendChild(bubble);
            win.scrollTop = win.scrollHeight;
        }

        function askAgent() {
            if (!currentCompany) return;
            const q = document.getElementById("agent-q").value.trim();
            if (!q) return;
            document.getElementById("agent-q").value = '';
            
            addChat('user', esc(q));
            addChat('agent', '<span class="typing">Analyzing data...</span>');
            
            const d = currentCompany;
            const claims = d.claims || [];
            const lq = q.toLowerCase();
            
            setTimeout(() => {
                const win = document.getElementById("chat-window");
                win.removeChild(win.lastChild);
                
                let res = "I don't have enough verified evidence to answer that.";
                if (lq.includes("financial") || lq.includes("revenue") || lq.includes("money") || lq.includes("result")) {
                    const rev = getVal(claims, 'financials.revenue');
                    const op = getVal(claims, 'financials.operating_result');
                    if (rev && rev.amount) {
                        res = "Financials for " + esc(d.name) + ":<br>Latest reported revenue: <strong>" + fmtCurr(rev.amount) + "</strong> (FY " + rev.year + ").<br>Operating result: <strong>" + fmtCurr(op && op.amount) + "</strong>.";
                    } else {
                        res = "No financial records were found in the register for this company.";
                    }
                } else if (lq.includes("who") || lq.includes("lead") || lq.includes("run") || lq.includes("ceo") || lq.includes("board")) {
                    const people = claims.filter(c => c.field.startsWith('people.role') && c.value && c.value.name);
                    if (people.length) {
                        res = "Key people:<br>" + people.slice(0, 3).map(p => esc(p.value.name) + " (" + esc(p.value.role || 'Role') + ")").join('<br>');
                    } else {
                        res = "No public role records were found for this company.";
                    }
                } else if (lq.includes("where") || lq.includes("office") || lq.includes("location") || lq.includes("address")) {
                    const locs = claims.filter(c => c.field === 'locations.subunit.name' && c.value && c.value.name);
                    if (locs.length) {
                        res = "Registered workplaces:<br>" + locs.slice(0, 5).map(l => "&bull; " + esc(l.value.name)).join('<br>');
                    } else {
                        res = "The registered business address is in " + esc(d.muni || "an unknown municipality") + ". No separate subunits were found.";
                    }
                } else if (lq.includes("what") || lq.includes("do") || lq.includes("about") || lq.includes("brief")) {
                    res = "Overview:<br>" + esc(d.summary || 'No summary available.');
                }
                addChat('agent', res);
            }, 600);
        }

        function toggleTheme() {
            const doc = document.documentElement;
            if (doc.getAttribute('data-theme') === 'dark') doc.removeAttribute('data-theme');
            else doc.setAttribute('data-theme', 'dark');
        }

        document.getElementById("search").addEventListener("input", renderList);
        renderList();
        if (DATA.length > 0) selectCompany(DATA[0].org);
        renderList();
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
        "changes": env.get("changes") or [],
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
    json_data = json.dumps(rows, ensure_ascii=False, default=str).replace("</", "<\\/")
    target.write_text(HTML.replace("__DATA__", json_data), encoding="utf-8")
    print(f"Wrote {target} with {len(rows)} companies")

if __name__ == "__main__":
    main()