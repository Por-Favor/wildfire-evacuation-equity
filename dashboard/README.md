# Wildfire Evacuation Equity Dashboard

An interactive **equity-audit and planning tool** for emergency managers, built with [Plotly Dash](https://dash.plotly.com/). It is **retrospective and analytical** — it surfaces how California wildfire evacuation alerting has played out historically, by county and by community vulnerability. **It is not a real-time alerting system and does not issue or recommend issuing live evacuation orders.**

## What it shows

- **Tab 1 — County Report Card.** Click any California county on the map to see its historical median alert lag, its community-vulnerability breakdown (CDC SVI access barriers), its major fires (2021–2025), and **pre-season planning recommendations** tailored to that county's vulnerability profile.
- **Tab 2 — Historical Response Patterns.** Enter a fire's characteristics (county, size category, time of day) to see **how fires with a similar profile were handled historically** in that county — the fraction that escalated to evacuation, framed as a planning reference, **not** a live recommendation.

## Run it

```bash
# from the repo root
cd dashboard
pip install -r ../requirements.txt     # if not already installed
python app.py
```

Then open <http://127.0.0.1:8050>.

## Data it needs

The app loads one file, **`dashboard/data/merged_fire_svi.csv`** (included), at startup. It also fetches a California county GeoJSON from a public Plotly URL on first load (needs internet once; the map degrades gracefully if offline).

## AI-use disclosure

This dashboard's application code was implemented with the help of **AI coding assistance (Anthropic's Claude / Claude Code)**, working from the team's own specifications, design decisions, and framing. The analysis, findings, and interpretation behind it are the team's own. See the root [`README.md`](../README.md) for the full disclosure.
