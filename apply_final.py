from pathlib import Path
import ast

def patch(path, old, new, label):
    p = Path(path)
    if not p.exists():
        print(f"MISSING {path}"); return
    text = p.read_text(encoding="utf-8-sig")
    if new in text:
        print(f"ALREADY {label}"); return
    if old not in text:
        print(f"NO-MATCH {label}"); return
    text = text.replace(old, new, 1)
    if path.endswith(".py"):
        ast.parse(text)
    p.write_text(text, encoding="utf-8", newline="\n")
    print(f"PATCHED {label}")

# 1. Patch summary.py to include Hiring and Public Activity
patch(
    "src/norway_company_agent/summary.py",
    "    unknowns = _stated_unknowns(envelope)",
    """    # Hiring
    hiring = _claim_value(envelope, "jobs.has_active_postings")
    if hiring is True:
        lines.append("Hiring: Active job postings found on NAV.")
    elif hiring is False:
        lines.append("Hiring: No active job postings found on NAV.")
    else:
        lines.append("Hiring: NAV was not checked or returned no data.")

    # Public Activity
    activities = _claims_with_prefix(envelope, "activity.") + _claims_with_prefix(envelope, "web.activity.")
    if activities:
        lines.append(f"Public activity: {len(activities)} dated event(s) found (e.g. role changes, registrations).")
    else:
        lines.append("Public activity: No dated public activity found in the checked sources.")

    unknowns = _stated_unknowns(envelope)""",
    "summary.py hiring/activity"
)

# 2. Patch build_viewer.py
V = "scripts/build_viewer.py"

# 2a. Add Hiring and Activity tabs
patch(
    V,
    """<div class="tab" onclick="switchTab(event, \\'ch\\')">Changes</div></div>""",
    """<div class="tab" onclick="switchTab(event, \\'ch\\')">Changes</div><div class="tab" onclick="switchTab(event, \\'hi\\')">Hiring</div><div class="tab" onclick="switchTab(event, \\'ac\\')">Activity</div></div>""",
    "viewer tabs"
)

# 2b. Add JS variables for jobs and activities before renderCenter returns
old_js = """            const locRows = claims.filter(c => c.field === 'locations.subunit.name').map(c => {
                const v = c.value || {};
                const m = claims.find(x => x.field === 'locations.subunit.municipality' && (x.value || {}).subunit_orgnr === v.subunit_orgnr);
                return '<tr><td style="font-weight:600">' + esc(v.name || v.subunit_orgnr) + '</td><td style="color:var(--text-muted)">' + esc((m && m.value || {}).municipality || '-') + '</td></tr>';
            }).join('');"""

new_js = old_js + """

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
            }).join('');"""

patch(V, old_js, new_js, "viewer js vars")

# 2c. Append the new tab contents
old_end = """(d.changes && d.changes.length ? d.changes.map(ch => '<tr><td style="font-weight:600">' + esc(ch.field) + '</td><td style="color:var(--text-muted)">' + esc(ch.old_value) + '</td><td style="color:var(--green)">' + esc(ch.new_value) + '</td><td><span class="claim-badge">' + esc(ch.change_type) + '</span></td></tr>').join('') : '<tr><td colspan="4" style="color:var(--text-muted)">No changes detected.</td></tr>') + '</tbody></table></div>';"""

new_end = """(d.changes && d.changes.length ? d.changes.map(ch => '<tr><td style="font-weight:600">' + esc(ch.field) + '</td><td style="color:var(--text-muted)">' + esc(ch.old_value) + '</td><td style="color:var(--green)">' + esc(ch.new_value) + '</td><td><span class="claim-badge">' + esc(ch.change_type) + '</span></td></tr>').join('') : '<tr><td colspan="4" style="color:var(--text-muted)">No changes detected.</td></tr>') + '</tbody></table></div>' +
                '<div id="tc-hi" class="tab-content"><h3 style="font-family:var(--font-serif);font-size:20px;margin-bottom:12px">Hiring</h3>' + 
                (jobRows || '<p style="color:var(--text-muted)">No active postings found in the checked sources.</p>') + '</div>' +
                '<div id="tc-ac" class="tab-content"><h3 style="font-family:var(--font-serif);font-size:20px;margin-bottom:12px">Public Activity</h3><table><thead><tr><th>Event</th><th>Date</th><th>Details</th></tr></thead><tbody>' + 
                (actRows || '<tr><td colspan="3" style="color:var(--text-muted)">No dated public activity found in the checked sources.</td></tr>') + '</tbody></table></div>';"""

patch(V, old_end, new_end, "viewer tab contents")

# 3. Patch README and SPEC
patch("README.md", "- **External APIs:**", "- **Profile sections:** Overview, Financials, Leadership, Locations, Hiring, Activity, Changes.\n- **External APIs:**", "README profile sections")
patch("SPEC.md", "- **External APIs:** Brreg Enhetsregisteret", "- **Profile sections:** Overview, Financials, Leadership, Locations, Hiring, Activity, Changes.\n\n- **External APIs:** Brreg Enhetsregisteret", "SPEC profile sections")

print("ALL DONE")