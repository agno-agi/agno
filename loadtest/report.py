"""Render results.json -> report.html : a one-glance visual dashboard.

Groups tests by category, color-codes PASS/FAIL/WARN/SKIP, shows a summary
banner + per-test evidence. Open report.html in a browser.
"""

import json
import os
import time

RESULTS = os.environ.get("RESULTS", "results.json")
OUT = os.environ.get("REPORT", "report.html")

COLORS = {"PASS": "#1a7f37", "FAIL": "#cf222e", "WARN": "#9a6700", "SKIP": "#6e7781"}
BG = {"PASS": "#dafbe1", "FAIL": "#ffebe9", "WARN": "#fff8c5", "SKIP": "#f6f8fa"}


def main():
    data = json.load(open(RESULTS))
    results = data["results"]
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(results)
    overall = "FAIL" if counts["FAIL"] else ("WARN" if counts["WARN"] else "PASS")

    # group by category
    cats = {}
    for r in results:
        cats.setdefault(r["category"], []).append(r)

    gen = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data.get("generated_at", time.time())))

    rows = []
    for cat, items in cats.items():
        rows.append(f'<h2 class="cat">{cat}</h2>')
        for r in items:
            ev = "".join(
                f"<div class='ev'><span>{k}</span><code>{json.dumps(v)}</code></div>" for k, v in r["evidence"].items()
            )
            rows.append(f"""
            <div class="card" style="border-left:6px solid {COLORS[r['status']]}">
              <div class="head">
                <span class="badge" style="background:{COLORS[r['status']]}">{r['status']}</span>
                <span class="comp">{r['component'] or '-'}</span>
                <span class="name">{r['name']}</span>
                <span class="dur">{r['duration']}s</span>
              </div>
              <div class="detail">{r['detail']}</div>
              <details><summary>evidence</summary><div class="evwrap">{ev}</div></details>
            </div>""")

    tiles = "".join(
        f"<div class='tile' style='background:{BG[s]};color:{COLORS[s]}'><div class='num'>{counts[s]}</div><div>{s}</div></div>"
        for s in ("PASS", "FAIL", "WARN", "SKIP")
    )

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>AgentOS Job Queue — E2E Report</title>
<style>
 body{{font:14px -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f8fa;color:#1f2328}}
 header{{background:{COLORS[overall]};color:#fff;padding:20px 28px}}
 header h1{{margin:0;font-size:20px}} header .sub{{opacity:.9;font-size:13px;margin-top:4px}}
 .summary{{display:flex;gap:12px;padding:20px 28px;flex-wrap:wrap}}
 .tile{{border-radius:10px;padding:16px 22px;text-align:center;min-width:90px;font-weight:600}}
 .tile .num{{font-size:28px}}
 main{{padding:0 28px 40px;max-width:1000px}}
 .cat{{font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:#6e7781;margin:22px 0 8px}}
 .card{{background:#fff;border:1px solid #d0d7de;border-radius:8px;margin:8px 0;padding:12px 14px}}
 .head{{display:flex;align-items:center;gap:10px}}
 .badge{{color:#fff;font-weight:700;font-size:11px;padding:2px 8px;border-radius:20px}}
 .comp{{font-size:12px;color:#6e7781;min-width:70px}}
 .name{{font-weight:600;flex:1}} .dur{{color:#6e7781;font-size:12px}}
 .detail{{margin:6px 0 4px;color:#57606a;font-size:13px}}
 details{{margin-top:4px}} summary{{cursor:pointer;color:#0969da;font-size:12px}}
 .evwrap{{margin-top:6px;background:#f6f8fa;border-radius:6px;padding:6px 10px}}
 .ev{{display:flex;gap:10px;font-size:12px;padding:2px 0}}
 .ev span{{color:#6e7781;min-width:170px}} .ev code{{color:#1f2328;word-break:break-all}}
</style></head><body>
<header>
  <h1>AgentOS Job Queue — E2E Feature Report &nbsp; [{overall}]</h1>
  <div class="sub">{total} tests · {data.get('base_url','')} · {gen}</div>
</header>
<div class="summary">{tiles}</div>
<main>{''.join(rows)}</main>
</body></html>"""

    with open(OUT, "w") as f:
        f.write(html)
    print(f"report -> {OUT}  (overall {overall}: PASS={counts['PASS']} FAIL={counts['FAIL']} WARN={counts['WARN']} SKIP={counts['SKIP']})")


if __name__ == "__main__":
    main()
