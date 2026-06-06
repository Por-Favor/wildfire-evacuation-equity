# Wildfire Evacuation Equity Audit In California

**A retrospective, data-driven audit of *where* and *for whom* wildfire evacuation alerting in California has been slowest, built for emergency managers and planners.**

WiDS Datathon 2026 · **Route 1: Accelerating Equitable Evacuations** · WatchDuty wildfire data + CDC Social Vulnerability Index.

---

## Team

| Member | Contributions |
|---|---|
| **Nyan Lin Thura**  ("Lin") | Data pipeline, California geographic-filter fix, CDC SVI integration, equity analysis, ML modeling (classifier + equity regression) |
| **Yu-Wen Wang**  ("NiNi") | Escalation-pattern analysis, perimeter-timing analysis, evacuation-zone analysis, Eaton Fire case study, and the submission dashboard |

Pasadena City College: WiDS University Datathon 2026, Route 1.

---

## The problem and the question

When a wildfire starts, the gap between when it is first seen and when an evacuation order goes out can be the difference between a safe evacuation and a deadly one. That gap may not be shared equally across communities.

> **Our central question:** *How long does it take for a fire from being seen to an evacuation order and does that gap become wider on socially vulnerable communities?*

> It will audit *historical* California wildfire data to surface where alerting has been slow and which vulnerable communities are most exposed. Everything in this repository, including the analysis, the dashboard, and the models are framed for **planning and review**, not for issuing or recommending live evacuation orders.


## Data

- **WatchDuty**: 9 datasets (fire events, changelogs, evacuation zones, fire perimeters), 2021–2025.
- **CDC/ATSDR Social Vulnerability Index (SVI) 2022**: community vulnerability by California census tract; using **measured access barriers** (limited English, no vehicle, age 65+, disability, poverty, no internet)

> **Raw WatchDuty data is not redistributed here** (it is large and not ours to redistribute). Obtain it from the **WiDS Datathon 2026 Kaggle competition page** and place the raw CSVs in `data/raw/` (see *How to reproduce*). The small, derived/processed CSVs the analysis produces **are** included under `data/processed/` so the later sections and the dashboard run without the raw data.

**Population filtering:**

```
~15,000  California wildfires logged
   ↓
~11,600  monitored (including changelog activity)
   ↓
   ~250  escalated to an evacuation order   ← the equity-analysis population
```

## Methods

1. **Data pipeline.** Parse the WatchDuty changelog JSON into per-fire timelines (first sighting, rate-of-spread report, structure threat, evacuation advisory/warning/order). **California filter fix:** an initial address-text regex missed ~85% of California fires (WatchDuty often omits the state on CA addresses); we switched to a **geographic lat/lng bounding box + reverse geocoding**, which recovered them — California fires went from ~2,500 (regex) to ~14,000, and evacuation-order fires from a handful to ~250. Catching this before modeling was critical.
2. **CDC SVI integration.** Aggregate tract-level SVI to county level (population-weighted) and join to each fire's county.
3. **Two ML models** (notebook Section 18):
   - **A classifier** predicting whether a fire will require an evacuation order from its early signals — cross-validated **ROC-AUC ≈ 0.94** (Random Forest; 0.92–0.96 across logistic regression, random forest, and XGBoost). SHAP confirms it keys on **operational danger signals** (fire size, rate of spread, notification escalation) — **not** demographics.
   - **An equity regression** that isolates the effect of vulnerability on *catastrophic* alert delay after controlling for fire severity.

## Key findings

**1. The equity finding (stated with its nuance).**
Community vulnerability does **not** change the *typical* evacuation response time. T
he median alert lag is roughly flat (~50 min) across vulnerability levels. **But** vulnerable communities are far more likely to suffer **catastrophic** delays (>6 hours): about **2.9%** of evacuation-order fires in the least-vulnerable quartile vs **18.2%** in the most-vulnerable 
(roughly **6× higher across quartiles (≈6.5× on a low- vs high-vulnerability split)**) and this disparity is **statistically significant (p = 0.002) and robust to controls for fire severity**.
*The honest claim is "vulnerability doesn't slow the typical response, but it sharply raises the risk of catastrophic delay"*

**2. Escalation patterns (Nini).** Only **~2.1%** of fires follow the expected advisory → warning → order escalation; about **64%** jump straight to an evacuation order with no prior warning. Residents in those areas get no "get ready" signal.

**3. Perimeter timing (Nini).** About **81%** of evacuation orders are issued *before* any approved fire perimeter exists (median ~7.5 hr to first perimeter vs ~1.4 hr to first order). Life-safety decisions are driven by early signals, not mapped boundaries.

**4. Eaton Fire case study (Nini).** In the January 2025 Eaton Fire (Los Angeles), evacuation orders went out **47 minutes** after the fire was first recorded before any warning with the same skipped-escalation pattern seen across the dataset.

## The dashboard

An interactive **equity-audit and planning tool** (`dashboard/app.py`, Plotly Dash). It is framed throughout for planning and after-action review, not live alerting:

- **Tab 1 — County Report Card:** click any California county to see its historical alert lag, community-vulnerability breakdown, major fires (2021–2025), and **pre-season planning recommendations**.
- **Tab 2 — Historical Response Patterns:** enter a fire's characteristics to see **how fires with a similar profile were handled historically** in that county, as a planning reference.

See [`dashboard/README.md`](dashboard/README.md) to run it.

## AI-use disclosure

**This project used AI coding assistance (Anthropic's Claude / Claude Code) to help implement the dashboard.** The team wrote the specifications, design decisions, framing, and data choices; AI assistance was used to help write and refactor the dashboard's application code from those specifications. **All analytical work — the data pipeline, the equity analysis, the modeling, the findings, the framing, and their interpretation — is the team's own.** We disclose this openly in the interest of competition integrity and transparency.

## Limitations

- **Small sample.** The equity analysis rests on ~250 evacuation-order fires, and the catastrophic-delay finding on ~20 extreme-delay cases. The direction is clear and statistically significant, but the precise magnitude is uncertain.
- **County-grain vulnerability.** SVI is measured at the county level here; tract-level SVI (future work) would sharpen the geographic precision.
- **Observational.** We show an association that survives controls for fire severity.

## How to reproduce

```bash
# 1. Clone and create an environment
git clone <this-repo-url>
cd wildfire-evacuation-equity
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. (Optional — only to re-run the full pipeline from scratch)
#    Download the raw WatchDuty CSVs from the WiDS 2026 Kaggle competition page
#    and place them in data/raw/. The processed CSVs in data/processed/ are
#    already included, so the later analysis sections and the dashboard run
#    without the raw data.

# 3. Run the notebook (outputs are already embedded, so this is optional)
jupyter lab notebooks/notebook_v1_merged.ipynb

# 4. Run the dashboard
cd dashboard
python app.py        
```

**On Kaggle:** the notebook auto-detects `/kaggle/input` and uses the dual-path data loading at the top of Section 1. Attach **two Kaggle Datasets** and set their slugs in that cell (marked `TODO`):
1. the **WatchDuty competition data** (raw CSVs), and
2. the team's **CDC SVI dataset** (`cali_census_tracts.csv`).
The notebook ships with all outputs embedded, so it is readable top-to-bottom without re-execution.

## Repository structure

```
wildfire-evacuation-equity/
├── README.md                         # this file
├── requirements.txt                  # all notebook + dashboard dependencies
├── .gitignore
├── notebooks/
│   └── notebook_v1_merged.ipynb      # the complete submission notebook
│                                     #   (pipeline → EDA → equity → escalation →
│                                     #    perimeter → Eaton case study → ML modeling)
├── dashboard/
│   ├── app.py                        # the equity-audit / planning dashboard
│   ├── data/merged_fire_svi.csv      # data the dashboard loads
│   └── README.md                     # how to run the dashboard
├── data/processed/                   # small derived CSVs (committed; <100 MB each)
├── outputs/figures/                  # saved analysis + ML figures
├── src/parsing.py                    # changelog-parsing helpers used by the notebook
├── slides/WiDS_Slides.pdf            # presentation deck
└── dashboard_demo/demo_video_link.mov           # dashboard demo video link
```

## Attribution

| Area | Lead |
|---|---|
| Data pipeline, CA geographic-filter fix, changelog parsing | Lin |
| CDC SVI integration, county-level equity analysis | Lin |
| ML modeling (classifier + equity regression, SHAP) | Lin |
| Escalation-pattern analysis | Nini |
| Perimeter-timing analysis | Nini |
| Evacuation-zone analysis & Eaton Fire case study | Nini |
| Submission dashboard | Nini |
| Consolidated notebook & presentation | Joint |

## Links
- **Slide deck:** [`slides/WiDS_Slides.pdf`](slides/WiDS_Slides.pdf)
- **Dashboard demo video:** see [`dashboard_demo/demo_video_link.mov`](dashboard_demo/demo_video_link.mov)
