#!/usr/bin/env python3
"""Sammelt die offiziellen zeit.de-Artikel-URLs der einzelnen Folgen aus dem
Serien-Archiv und mappt sie per Veroeffentlichungs-DATUM auf die Folgen.

Das lokale Backup enthaelt pro Folge nur die generische Serien-URL. Die
folgenspezifischen Artikel-Links stehen im zeit.de-Archiv
(/serie/servus-gruezi-hallo?p=1..N). Titel-Matching scheitert bei alten Folgen
(anderer Kicker "Politikpodcast:" statt "Alpenpodcast:", abweichende Titel),
darum matchen wir ueber das <time datetime>-Feld jedes Teasers (eine Folge/Woche).

Schreibt zeit_links.json: { "YYYY-MM-DD": [[url, titel], ...] }
Mit sgh-episodes.json als Argument wird die Trefferquote (Datum +-3 Tage) berichtet.

Usage: python3 fetch_zeit_links.py [sgh-episodes.json]
"""
import urllib.request, re, html, json, sys
from datetime import date

BASE = "https://www.zeit.de/serie/servus-gruezi-hallo?p="
UA = {"User-Agent": "Mozilla/5.0"}
HREF = re.compile(r'href="(https://www\.zeit\.de/[a-z-]+/\d{4}-\d{2}/[a-z0-9-]+)"')
TIME = re.compile(r'datetime="(\d{4}-\d{2}-\d{2})')
TITLE = re.compile(r'title="(?:[^":]{2,20}:\s*)?([^"]+)"')

def fetch(p):
    return urllib.request.urlopen(urllib.request.Request(BASE + str(p), headers=UA),
                                  timeout=30).read().decode("utf-8", "replace")

def main():
    by_date = {}
    n = 0
    for p in range(1, 13):
        try:
            h = fetch(p)
        except Exception as e:
            print(f"Seite {p}: Stop ({e})"); break
        arts = re.findall(r"<article\b.*?</article>", h, re.S)
        if not arts:
            print(f"Seite {p}: keine Artikel -> Stop"); break
        found = 0
        for a in arts:
            hu, tm = HREF.search(a), TIME.search(a)
            if hu and tm:
                tt = TITLE.search(a)
                title = html.unescape(tt.group(1)).strip() if tt else ""
                rec = [hu.group(1), title]
                by_date.setdefault(tm.group(1), [])
                if rec not in by_date[tm.group(1)]:
                    by_date[tm.group(1)].append(rec); n += 1; found += 1
        print(f"Seite {p}: {found} Folgen-Links")
    json.dump(by_date, open("zeit_links.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{n} Links / {len(by_date)} Daten -> zeit_links.json")

    if len(sys.argv) > 1:
        eps = json.load(open(sys.argv[1], encoding="utf-8"))
        def lookup(d):
            y, m, dd = map(int, d.split("-")); t = date(y, m, dd)
            for off in (0, -1, 1, -2, 2, -3, 3):
                k = date.fromordinal(t.toordinal() + off).isoformat()
                if k in by_date:
                    return by_date[k]
            return None
        hit = sum(1 for e in eps if lookup(e["date"]))
        print(f"\nMatch (Datum +-3 Tage) gegen {len(eps)} Folgen: {hit} Treffer, {len(eps)-hit} ohne Link")
        for e in eps:
            if not lookup(e["date"]):
                print("  miss:", e["date"], e["title"])

if __name__ == "__main__":
    main()
