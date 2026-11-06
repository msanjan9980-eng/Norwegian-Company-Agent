from pathlib import Path
import ast

p = Path("scripts/enforce_contract.py")
text = p.read_text(encoding="utf-8-sig")

# Check if it's actually called in the execution logic, not just defined
lines = text.splitlines()
already_called = any("_sanitize_web_claims(" in l and "def " not in l for l in lines)

if already_called:
    print("ALREADY called in the logic.")
else:
    patched = False
    new_lines = []
    for line in lines:
        new_lines.append(line)
        # Find where the envelope is parsed from the JSON line
        if "json.loads(" in line and "=" in line:
            # Extract the variable name (e.g., 'env' from 'env = json.loads(...)')
            var_name = line.split("=")[0].strip()
            indent = line[:len(line) - len(line.lstrip())]
            # Inject the call immediately after with the same indentation
            new_lines.append(f"{indent}_sanitize_web_claims({var_name})")
            patched = True
    
    if patched:
        text = "\n".join(new_lines) + "\n"
        ast.parse(text)
        p.write_text(text, encoding="utf-8", newline="\n")
        print("SUCCESS: Hooked _sanitize_web_claims directly into the JSON parsing loop.")
    else:
        print("NO-MATCH: Could not find json.loads in enforce_contract.py.")

ast.parse(p.read_text(encoding="utf-8"))
print("OK: enforce_contract.py parses")