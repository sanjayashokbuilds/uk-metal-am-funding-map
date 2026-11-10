# uk-metal-am-funding-map

The expensive part of metal 3D printing usually isn't the printing. It's proving the part is good enough to fly, go into a body or sit in a reactor, and a lot of that still means CT scanning finished parts one by one.

I wanted to see who in the UK is actually spending money on fixing that. UKRI publishes every project it funds, with the description each team wrote for itself, so this pulls those projects, keeps the ones about metal additive manufacturing that touch in-build monitoring, defect prediction, inspection or qualification, and works out which organisations keep showing up.

Every match keeps the sentence from the project's own description that put it there, so any row can be checked.

## What I found

Full report: [`output/report.md`](output/report.md). Every project: [`output/projects.csv`](output/projects.csv). Every organisation: [`output/organisations.csv`](output/organisations.csv).

- **73 funded projects, about £51.6m of public money, 96 companies.** 17 are still running.
- **Renishaw is the hub.** It's on 10 of the 73 projects, more than any other company, usually alongside the MTC, Sheffield and Imperial.
- **Only one project says outright that it wants to cut post-build inspection:** HIETA's deep-learning fault detection work. HIETA also has a live project with BAE Systems, Meggitt and Renishaw that runs to December 2026.
- **ATLAS ("Assurance through layer-wise anomaly sensing")** with AWE, Renishaw and OSSTEC finished in April 2026. When projects like that end, the partners who want to keep the capability need something commercial.
- **The biggest programme doesn't show up on description alone.** DECSAM (£38m, Airbus-led, runs to June 2028) has a generic UKRI description, but the partners' own announcements say it aims for in-process monitoring with closed-loop control "to reduce or eliminate HIP/CT where feasible" ([ASTM](https://amcoe.org/?p=7913)). Partners include Airbus, Renishaw, GKN Aerospace, the MTC and ASTM International UK.

## How a project gets a tier

| Tier | Meaning |
|---|---|
| A | its description explicitly aims to cut CT or post-build inspection |
| B | in-build monitoring or defect prediction for metal AM |
| C | qualification, certification, inspection or QA of metal AM parts |

A project only counts if its title or description mentions metal additive manufacturing (powder bed fusion, SLM, EBM, DED, metal AM). CT scans of patients and similar medical imaging are excluded.

## Run it

```bash
python3 ctmap.py                 # pulls, caches, writes output/
python3 ctmap.py --why "ATLAS"   # shows why a project was or wasn't included
```

No API key needed and nothing to install. Everything is cached in `.cache/`, so reruns take seconds.

## Notes

- Source: UKRI Gateway to Research. UK public funding only, so private R&D and EU projects aren't here yet.
- Project value is UKRI's figure and doesn't include industry contributions.
- Big groups are rolled up (all BAE Systems entities count as BAE Systems, and so on).
- Matching is keyword-based. Some relevant projects with vague descriptions will be missed (DECSAM is the obvious one), which is why it's noted separately above.
