from pathlib import Path
import ast, re

p = Path("scripts/enforce_contract.py")
text = p.read_text(encoding="utf-8-sig")

# Check if the call is already there
if "_sanitize_web_claims(env)" in text or "_sanitize_web_claims(envelope)" in text:
    print("ALREADY hooked up.")
else:
    # Find the main loop that processes the envelopes. 
    # It's usually `for envelope in ...` or `for env in ...`
    match = re.search(r'for\s+([a-zA-Z_]\w*)\s+in\s+envelopes:', text)
    if match:
        var_name = match.group(1)
        anchor = match.group(0)
        replacement = anchor + f"\n        _sanitize_web_claims({var_name})"
        text = text.replace(anchor, replacement, 1)
        ast.parse(text)
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"SUCCESS: Hooked _sanitize_web_claims({var_name}) into the main loop.")
    else:
        print("NO-MATCH: Could not find the loop. Please paste the main() function of enforce_contract.py.")

ast.parse(p.read_text(encoding="utf-8"))
print("OK: enforce_contract.py parses")