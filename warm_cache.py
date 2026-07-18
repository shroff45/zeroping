# warm_cache.py
# Run this ONCE after golden.db is created.
# Generates and caches all 4 narratives.
# After this, demo works even if Ollama is slow.

import json
import sys

# Force UTF-8 encoding for standard output to prevent Windows console encoding crashes
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from core.schemas import make_fixture_snapshot
from core.pipeline import run_pipeline
from llm.backend import OllamaBackend
from llm.grounding import build_allowlist, is_grounded
from llm.prompts import dashboard_messages, email_messages
from llm.fallbacks import dashboard_fallback, email_fallback
from llm.cache import cache_key, get as cache_get, put as cache_put

def clean_json_str(s: str) -> str:
    s = s.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()

print("Starting cache warmup...")
print("This may take 2-5 minutes on first run.")
print()

snap = make_fixture_snapshot()
result = run_pipeline(snap)
llm = OllamaBackend()

if not llm.health():
    print("ERROR: Ollama is not running.")
    print("Start Ollama and try again.")
    exit(1)

allowed = build_allowlist(result)

# 1. Dashboard narrative
print("Generating dashboard narrative...")
key = cache_key(result.snapshot_hash, "dashboard")
if cache_get(key):
    print("  Already cached - skipping")
else:
    msgs = dashboard_messages(result)
    raw = llm.generate(msgs)
    if raw:
        raw_cleaned = clean_json_str(raw)
        ok, violations = is_grounded(raw_cleaned, allowed)
        if ok:
            cache_put(key, raw_cleaned)
            data = json.loads(raw_cleaned)
            print("  CACHED [OK]")
            print(f"  Headline: {data.get('headline', '')[:60]}...")
        else:
            print("  GROUNDING FAILED [FAIL]")
            print(f"  Violations: {violations}")
            print("  Using fallback for demo")
            fb = dashboard_fallback(result)
            cache_put(key, json.dumps(fb))
    else:
        print("  LLM returned None - check Ollama (might have timed out loading model)")

# 2. Apex collection email
print()
print("Generating Apex collection email...")
apex = next(
    (a for a in result.anomalies.anomalies
     if a.severity == "ANOMALY"),
    None
)
if apex:
    key = cache_key(result.snapshot_hash, f"email_{apex.client}")
    if cache_get(key):
        print("  Already cached - skipping")
    else:
        msgs = email_messages(result, apex.client)
        raw = llm.generate(msgs)
        if raw:
            raw_cleaned = clean_json_str(raw)
            ok, violations = is_grounded(raw_cleaned, allowed)
            if ok:
                cache_put(key, raw_cleaned)
                data = json.loads(raw_cleaned)
                print("  CACHED [OK]")
                print(f"  Subject: {data.get('subject', '')}")
            else:
                print("  GROUNDING FAILED [FAIL]")
                print(f"  Violations: {violations}")
                fb = email_fallback(result, apex.client)
                cache_put(key, json.dumps(fb))
        else:
            print("  LLM returned None - check Ollama (might have timed out loading model)")
else:
    print("  No ANOMALY client found - check gates")

print()
print("=" * 50)
print("Cache warmup complete.")
print()
print("Verify cache file exists:")
import os
cache_path = "data/llm_cache.db"
if os.path.exists(cache_path):
    size = os.path.getsize(cache_path)
    print(f"  data/llm_cache.db exists ({size} bytes) [OK]")
else:
    print("  data/llm_cache.db NOT FOUND [FAIL]")

print()
print("Now turn WiFi OFF and run the app.")
print("It should load all narratives from cache instantly.")
