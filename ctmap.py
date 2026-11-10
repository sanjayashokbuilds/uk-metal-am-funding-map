"""Who is paying to cut CT scans in metal 3D printing?

Pulls UKRI / Innovate UK projects from Gateway to Research, keeps the ones whose
own descriptions overlap NexusAM's product (in-build monitoring that predicts
part quality and reduces CT / X-ray inspection for metal powder-bed AM), and
ranks the organisations behind them. Every match keeps the sentence it came from.

    python ctmap.py            # fetch (cached) + build outputs
    python ctmap.py --probe    # print one raw project to check the data shape
"""
import csv
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.parse

API = "https://gtr.ukri.org/gtr/api"
HDR = {"Accept": "application/vnd.rcuk.gtr.json-v7", "User-Agent": "nexus-ct-funding-map (research)"}
CACHE = Path(".cache")
OUT = Path("output")

QUERIES = [
    "powder bed fusion in-situ monitoring",
    "powder bed fusion process monitoring",
    "additive manufacturing in-process monitoring",
    "additive manufacturing qualification",
    "additive manufacturing certification",
    "additive manufacturing computed tomography",
    "additive manufacturing X-ray inspection",
    "additive manufacturing non-destructive",
    "additive manufacturing defect detection",
    "additive manufacturing porosity",
    "laser powder bed fusion quality",
    "selective laser melting monitoring",
    "melt pool monitoring",
    "metal additive manufacturing machine learning",
    "additive manufacturing digital twin quality",
    "laser powder bed fusion",
    "powder bed fusion aerospace",
    "additive manufacturing aerospace components",
    "DECSAM additive manufacturing",
    "additive manufacturing inspection cost",
    "additive manufacturing sensor data",
    "metal 3D printing quality assurance",
    "additive manufacturing right first time",
]
PAGES_PER_QUERY = 5      # 100 results a page, results come back ranked by relevance
PAGE_SIZE = 100

# --- what counts as "metal AM" and as "Nexus's problem" -----------------------
METAL_AM = re.compile(
    r"powder[- ]bed fusion|\bL-?PBF\b|\bPBF-?LB\b|selective laser melting|\bSLM\b|electron beam melting|"
    r"\bEBM\b|directed energy deposition|\bDED\b|metal additive|metal 3D print|additive(ly)? manufactur\w* (of )?"
    r"(metal|titanium|nickel|aluminium|aluminum|steel|alloy|superalloy|inconel|Ti-?6Al)|"
    r"(metal|titanium|nickel|aluminium|steel|alloy) (parts?|components?) (produced|made|built) by additive",
    re.I)
AM_ANY = re.compile(r"additive(ly)? manufactur|3D[- ]print|powder[- ]bed|\bAM\b", re.I)

THEMES = {
    "ct_reduction": re.compile(
        r"(reduc\w*|eliminat\w*|replac\w*|avoid\w*|minimi[sz]\w*|remov\w*|cut\w*|lower\w*|without (the need for )?)"
        r"[^.]{0,80}(\bCT\b|computed tomography|X-?ray (CT|inspection|tomography)|post-?(build|process) inspection|"
        r"non-?destructive (testing|evaluation|inspection)|\bNDT\b|\bNDE\b|inspection (cost|time|burden))|"
        r"(\bCT\b|computed tomography|X-?ray (CT|inspection))[^.]{0,80}(expensive|costly|time-?consuming|bottleneck|"
        r"prohibitive)", re.I),
    "in_build_monitoring": re.compile(
        r"in-?situ (process )?(monitor\w*|sens\w*|inspection|measurement)|in-?process (monitor\w*|sens\w*|inspection|"
        r"quality)|melt[- ]?pool (monitor\w*|imag\w*|sens\w*)|layer-?wise (monitor\w*|imag\w*|inspection)|"
        r"process monitoring|real-?time (monitor\w*|defect|quality)|closed-?loop (control|feedback)", re.I),
    "defect_prediction": re.compile(
        r"(predict\w*|detect\w*|identif\w*|classif\w*|forecast\w*)[^.]{0,60}(defect|porosity|pore|lack of fusion|"
        r"keyhole|crack\w*|anomal\w*|part quality)|(machine learning|deep learning|neural network|artificial "
        r"intelligence|\bAI\b|\bML\b)[^.]{0,80}(defect|porosity|quality|anomal\w*)", re.I),
    "qualification": re.compile(
        r"qualif(y|ied|ication)|certif(y|ied|ication)|part acceptance|acceptance criteria|airworth\w*|"
        r"regulatory approval|cost of (qualification|certification)|repeatab\w*|reproducib\w*", re.I),
}
THEMES["inspection_qa"] = re.compile(
    r"inspect\w*|non-?destructive|\bNDT\b|\bNDE\b|computed tomography|\bX-?CT\b|\bCT\b|X-?ray|"
    r"quality (assurance|control)|\bQA\b|defect\w*|porosity|part quality|first[- ]time[- ]right|right[- ]first[- ]time", re.I)
THEME_LABEL = {"ct_reduction": "Cut CT / inspection", "in_build_monitoring": "In-build monitoring",
               "defect_prediction": "Defect prediction", "qualification": "Qualification",
               "inspection_qa": "Inspection / QA"}
THEME_WEIGHT = {"ct_reduction": 4, "in_build_monitoring": 3, "defect_prediction": 2, "qualification": 2,
                "inspection_qa": 1}
NEXUS = re.compile(r"nexus additive|nexusam", re.I)


def tier(themes):
    if "ct_reduction" in themes:
        return "A"
    if {"in_build_monitoring", "defect_prediction"} & set(themes):
        return "B"
    return "C"

PUBLIC = re.compile(r"\bNHS\b|\bNIHR\b|hospital|foundation trust|\btrust\b|council\b|ministry|royal centre for "
                    r"defence|defence science|\bDSTL\b|government|department for|\bMOD\b", re.I)
SUFFIX = re.compile(r"\b(ltd|limited|plc|llp|inc|group|holdings|uk|\(uk\)|\(united kingdom\)|united kingdom|the)\b|[.,()&]", re.I)


GROUPS = ["airbus", "bae systems", "rolls royce", "rolls-royce", "gkn", "renishaw", "boeing", "weir", "meggitt",
          "awe", "atomic weapons establishment", "siemens", "safran", "leonardo", "thales", "johnson matthey"]


def canon(name):
    low = re.sub(r"\bp\s*l\s*c\b", "plc", name.lower())
    low = low.replace("rolls-royce", "rolls royce").replace("atomic weapons establishment", "awe")
    for g in GROUPS:
        if low.startswith(g) or low.startswith("the " + g):
            return g.replace("-", " ")
    key = re.sub(r"\s+", " ", SUFFIX.sub(" ", low)).strip()
    return key or low


def group_label(name):
    k = canon(name)
    return {"awe": "AWE (Atomic Weapons Establishment)", "bae systems": "BAE Systems", "rolls royce": "Rolls-Royce",
            "gkn": "GKN Aerospace", "renishaw": "Renishaw", "airbus": "Airbus", "boeing": "Boeing",
            "weir": "Weir Group", "meggitt": "Meggitt", "johnson matthey": "Johnson Matthey"}.get(k, name)


ACADEMIC = re.compile(r"universit|college|school of|institute of technology|^the university|\bETH\b|EPFL|"
                      r"technische|polytechnic|politecnico", re.I)
RTO = re.compile(r"catapult|manufacturing technology centre|\bMTC\b|\bAMRC\b|\bTWI\b|national physical laboratory|"
                 r"\bNPL\b|research centre|research center|\bUKAEA\b|atomic energy|nuclear advanced manufacturing|"
                 r"high value manufacturing|national centre|welding institute|\bTWI\b|forming research centre|\bAFRC\b|"
                 r"advanced technology centre", re.I)


# --- fetching ------------------------------------------------------------------
def get(url, tries=4):
    CACHE.mkdir(exist_ok=True)
    key = CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:] + ".json")
    if key.exists():
        return json.loads(key.read_text())
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read().decode("utf-8"))
            key.write_text(json.dumps(data))
            time.sleep(0.25)
            return data
        except Exception as e:  # network blips on eduroam: retry, then skip
            if i == tries - 1:
                print(f"  ! skipped {url[:90]} ({e})")
                return None
            time.sleep(2 * (i + 1))


def search(q, page):
    url = f"{API}/projects?" + urllib.parse.urlencode({"q": q, "p": page, "s": PAGE_SIZE})
    d = get(url) or {}
    return d.get("project", []) or []


def fund_dates(p):
    st, en = p.get("start"), p.get("end")
    for l in ((p.get("links") or {}).get("link") or []):
        if l.get("rel") == "FUND":
            st = st or l.get("start")
            en = en or l.get("end")
    return st, en


def link_ids(p, rel):
    out = []
    for l in ((p.get("links") or {}).get("link") or []):
        if l.get("rel") == rel and l.get("href"):
            out.append(l["href"].rstrip("/").split("/")[-1])
    return out


_orgs = {}


def org_name(oid):
    if oid not in _orgs:
        d = get(f"{API}/organisations/{oid}") or {}
        _orgs[oid] = (d.get("name") or "").strip() or oid
    return _orgs[oid]


def fund_value(p):
    total = 0
    for fid in link_ids(p, "FUND"):
        d = get(f"{API}/funds/{fid}") or {}
        v = (d.get("valuePounds") or {})
        amt = v.get("amount") if isinstance(v, dict) else v
        try:
            total += float(amt or 0)
        except (TypeError, ValueError):
            pass
    return total


def participants(p):
    """Organisations on the project: lead + partners + collaborators."""
    names = {}
    pv = p.get("participantValues") or {}
    for part in (pv.get("participant") or []) if isinstance(pv, dict) else []:
        oid = part.get("organisationId")
        nm = (part.get("organisationName") or "").strip()
        if oid or nm:
            names[oid or nm] = nm or org_name(oid)
    for rel in ("LEAD_ORG", "PARTICIPANT_ORG", "COLLAB_ORG", "PP_ORG"):
        for oid in link_ids(p, rel):
            names.setdefault(oid, org_name(oid))
    lead = [org_name(o) for o in link_ids(p, "LEAD_ORG")]
    merged = {}
    for n in names.values():
        if n:
            k = canon(n)
            # keep the nicest-looking spelling (mixed case, longest)
            if k not in merged or (merged[k].isupper() and not n.isupper()):
                merged[k] = n
    return (lead[0] if lead else ""), sorted(merged.values())


def ts(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return str(ms or "")[:10]


# --- matching --------------------------------------------------------------------
def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if len(s.strip()) > 20]


MEDICAL_IMAGING = re.compile(r"patient|MRI|clinical|radiolog|scan of the (body|patient)", re.I)


def match(p):
    text = " ".join(filter(None, [p.get("title"), p.get("abstractText"), p.get("techAbstractText"),
                                  p.get("potentialImpact")]))
    if not METAL_AM.search(text):
        return None
    themes, evidence = [], {}
    for name, rx in THEMES.items():
        for s in sentences(text):
            if name == "ct_reduction" and MEDICAL_IMAGING.search(s):
                continue
            if rx.search(s) and (AM_ANY.search(s) or METAL_AM.search(text)):
                themes.append(name)
                evidence[name] = s[:400]
                break
    if not themes:
        return None
    score = sum(THEME_WEIGHT[t] for t in themes)
    return themes, evidence, score


def kind(name):
    if ACADEMIC.search(name):
        return "academic"
    if PUBLIC.search(name):
        return "public body"
    if RTO.search(name):
        return "research centre"
    return "company"


# --- main ----------------------------------------------------------------------------
def main():
    if "--why" in sys.argv:
        term = sys.argv[sys.argv.index("--why") + 1]
        for f in CACHE.glob("*projects*.json"):
            for p in (json.loads(f.read_text()).get("project") or []):
                if re.search(term, p.get("title") or "", re.I):
                    text = " ".join(filter(None, [p.get("title"), p.get("abstractText"), p.get("techAbstractText"),
                                                  p.get("potentialImpact")]))
                    print("TITLE:", p.get("title"))
                    print("metal AM match:", bool(METAL_AM.search(text)))
                    print("result:", match(p))
                    print("TEXT:", text[:1500], "\n")
                    return
        print("not in cache")
        return
    if "--probe" in sys.argv:
        p = search(QUERIES[0], 1)[0]
        print(json.dumps({k: p.get(k) for k in ("title", "leadFunder", "grantCategory", "status", "start", "end",
                                                "participantValues", "links")}, indent=1)[:4000])
        return

    found = {}
    for q in QUERIES:
        n_before = len(found)
        for page in range(1, PAGES_PER_QUERY + 1):
            batch = search(q, page)
            for p in batch:
                found.setdefault(p.get("id"), p)
            if len(batch) < PAGE_SIZE:
                break
        print(f"{q!r}: +{len(found) - n_before} new (total {len(found)})")

    rows = []
    for pid, p in found.items():
        m = match(p)
        if not m:
            continue
        themes, evidence, score = m
        lead, orgs = participants(p)
        st, en = fund_dates(p)
        rows.append({
            "title": (p.get("title") or "").strip(),
            "funder": p.get("leadFunder") or "",
            "category": p.get("grantCategory") or "",
            "status": p.get("status") or "",
            "start": ts(st),
            "end": ts(en),
            "value_gbp": round(fund_value(p)),
            "lead": lead,
            "organisations": "; ".join(orgs),
            "companies": "; ".join(o for o in orgs if kind(o) == "company"),
            "tier": tier(themes),
            "nexus_own_project": any(NEXUS.search(o) for o in orgs),
            "themes": ", ".join(THEME_LABEL[t] for t in themes),
            "score": score,
            "ct_evidence": evidence.get("ct_reduction", ""),
            "monitoring_evidence": evidence.get("in_build_monitoring", ""),
            "defect_evidence": evidence.get("defect_prediction", ""),
            "qualification_evidence": evidence.get("qualification", "") or evidence.get("inspection_qa", ""),
            "link": f"https://gtr.ukri.org/projects?ref={pid}" if pid else "",
            "_orgs": orgs,
            "_themes": themes,
        })
    print(f"\n{len(found)} projects scanned, {len(rows)} match Nexus's problem")
    rows.sort(key=lambda r: (r["tier"], -r["score"], r["end"]))
    write(rows)


def write(rows):
    OUT.mkdir(exist_ok=True)
    pub = [k for k in rows[0].keys() if not k.startswith("_")] if rows else []
    with (OUT / "projects.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=pub, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    today = datetime.now(timezone.utc).date().isoformat()
    orgs = defaultdict(lambda: {"projects": 0, "value": 0, "themes": set(), "latest_end": "", "titles": [],
                                "partners": defaultdict(int), "live": 0, "name": ""})
    for r in rows:
        for o in r["_orgs"]:
            d = orgs[canon(o)]
            label = group_label(o)
            if label != o:
                d["name"] = label
            elif not d["name"] or (d["name"].isupper() and not o.isupper()):
                d["name"] = o
            d["projects"] += 1
            d["value"] += r["value_gbp"]
            d["themes"].update(r["_themes"])
            d["latest_end"] = max(d["latest_end"], r["end"])
            d["live"] += r["end"] >= today
            d["titles"].append(r["title"])
            for other in r["_orgs"]:
                if canon(other) != canon(o):
                    d["partners"][other] += 1

    org_rows = []
    for _key, d in orgs.items():
        name = d["name"]
        top_partners = sorted(d["partners"].items(), key=lambda kv: -kv[1])[:5]
        org_rows.append({
            "organisation": name, "type": kind(name), "projects": d["projects"], "live_projects": d["live"],
            "total_project_value_gbp": d["value"], "latest_end": d["latest_end"],
            "works_on_ct_reduction": "ct_reduction" in d["themes"],
            "themes": ", ".join(THEME_LABEL[t] for t in THEME_LABEL if t in d["themes"]),
            "frequent_partners": "; ".join(f"{p} ({n})" for p, n in top_partners),
            "example_project": d["titles"][0],
        })
    org_rows.sort(key=lambda r: (r["type"] != "company", -r["works_on_ct_reduction"], -r["projects"],
                                 -r["total_project_value_gbp"]))
    with (OUT / "organisations.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(org_rows[0].keys()) if org_rows else ["organisation"])
        w.writeheader()
        w.writerows(org_rows)

    report(rows, org_rows, today)
    print(f"Wrote {OUT/'projects.csv'}, {OUT/'organisations.csv'}, {OUT/'report.md'}")


def md(header, body):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in row) + " |" for row in body]
    return "\n".join(out)


def report(rows, org_rows, today):
    companies = [o for o in org_rows if o["type"] == "company" and not NEXUS.search(o["organisation"])]
    ct = [r for r in rows if "ct_reduction" in r["_themes"]]
    ending = sorted([r for r in rows if today <= r["end"] <= str(int(today[:4]) + 2) + today[4:]],
                    key=lambda r: r["end"])
    lines = [
        "# Who is paying to cut CT scans in metal 3D printing?",
        "",
        f"UK publicly funded projects (UKRI / Innovate UK, via Gateway to Research) whose own descriptions overlap "
        f"in-build monitoring, defect prediction or reducing CT inspection for metal additive manufacturing. "
        f"Run {today}.",
        "",
        f"- Projects matched: **{len(rows)}** (total project value £{sum(r['value_gbp'] for r in rows):,.0f})",
        f"- Tier A, explicitly aim to cut CT / inspection: **{sum(r['tier']=='A' for r in rows)}**",
        f"- Tier B, in-build monitoring or defect prediction: **{sum(r['tier']=='B' for r in rows)}**",
        f"- Tier C, qualification / inspection / QA of metal AM parts: **{sum(r['tier']=='C' for r in rows)}**",
        f"- Still running: **{sum(r['end'] >= today for r in rows)}**",
        f"- Companies involved: **{len(companies)}**",
        "",
        "## Companies working on this problem",
        "",
        md(["Company", "Projects", "Live", "Cut CT?", "Latest end", "Often works with"],
           [[o["organisation"], o["projects"], o["live_projects"], "yes" if o["works_on_ct_reduction"] else "",
             o["latest_end"], o["frequent_partners"][:90]] for o in companies[:30]]),
        "",
        "## Projects that say they want to cut CT or inspection",
        "",
        md(["Project", "End", "Value", "Lead", "In their words"],
           [[r["title"][:70], r["end"], f"£{r['value_gbp']:,.0f}", r["lead"][:40], r["ct_evidence"][:220]]
            for r in ct[:25]]),
        "",
        "## Ending in the next two years",
        "",
        "When a funded project finishes, the partners who want to keep the capability need a commercial tool.",
        "",
        md(["Tier", "Project", "End", "Companies"],
           [[r["tier"], r["title"][:70], r["end"], r["companies"][:110]] for r in ending[:30]]),
        "",
        "## Notes",
        "",
        "- Source: UKRI Gateway to Research public API. Only UK public funding; private R&D is invisible here.",
        "- A project is included only if its title or description mentions metal additive manufacturing **and** "
        "in-build monitoring, defect prediction or reducing CT / inspection. The sentence that triggered each tag is "
        "in `projects.csv`.",
        "- Project value is the UKRI fund value; industry contributions are not included.",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
