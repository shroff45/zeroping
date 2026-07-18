# LedgeAI

**Fully offline, on-device AI cashflow copilot for Indian SMEs.**

Four deterministic financial engines find the problems. A local Gemma 4 model
explains them in plain English and drafts the collection email and WhatsApp
follow-up. Nothing ever leaves the laptop.

**Tagline:** *The math finds the problem. Gemma explains it. You fix it. All on your device.*

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows (git-bash: source .venv/Scripts/activate)
pip install -r requirements.txt

# Seed the demo database (run once)
python data/seed.py
cp data/ledgeai.db data/golden.db

# Run the app
streamlit run app.py
```

## Architecture

See `ARCHITECTURE.md` and the master plan in `docs/`.

## The one rule

The LLM narrates numbers the engines computed. It never computes, estimates,
or invents. Enforced by a mechanism (grounding firewall), not a promise.

## License

Hackathon project — TBD.
