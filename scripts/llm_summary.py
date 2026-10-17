
import json
import os
import requests
from pathlib import Path

def generate_llm_summaries(input_file):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("No ANTHROPIC_API_KEY found. Skipping LLM synthesis.")
        return

    envs = []
    with open(input_file) as f:
        for line in f:
            if line.strip(): envs.append(json.loads(line))

    for env in envs:
        claims_summary = "\n".join([f"- {c['field']}: {c.get('value')} (Availability: {c['availability']})" for c in env.get("claims", [])])
        prompt = f"Write a 2-sentence professional summary of this company based ONLY on these facts. Do not invent anything. If facts are missing, say so.\n\n{claims_summary}"
        
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-3-haiku-20240307", "max_tokens": 150, "messages": [{"role": "user", "content": prompt}]},
                timeout=10
            )
            resp.raise_for_status()
            env["summary"] = resp.json()["content"][0]["text"].strip()
        except Exception as e:
            print(f"LLM failed for {env['organisation_number']}: {e}")
            # Keep existing template summary

    with open(input_file, "w", encoding="utf-8") as f:
        for env in envs:
            f.write(json.dumps(env) + "\n")
    print(f"LLM synthesis completed for {len(envs)} envelopes.")

if __name__ == "__main__":
    generate_llm_summaries("out/cited-envelopes.jsonl")
