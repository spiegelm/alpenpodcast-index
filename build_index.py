#!/usr/bin/env python3
"""Build a searchable episode index for the ZEIT podcast "Servus. Grüezi. Hallo."
from a local podcast database backup.

Reads the SGH feed (feeds.simplecast.com/br4J_MDH) out of the backup, cleans the
show notes (drops the repeated ad/subscription footer), assigns a chronological
running number, and writes three artifacts into the project folder:

    sgh-episodes.json   structured data, one object per episode
    sgh-episodes.csv    same data, spreadsheet-friendly
    sgh-index.html      self-contained, offline searchable page (data embedded)

Usage:  python3 build_index.py [path-to-backup.db]
Stdlib only (sqlite3, json, csv, html, re, datetime).
"""
import sqlite3, json, csv, html, re, sys, datetime
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "podcast-backup-2026-05-28.db")
FEED_URL = "https://feeds.simplecast.com/br4J_MDH"
OUT = Path(".")

# A paragraph is footer boilerplate (repeated on every episode) if it matches any
# of these. We keep all topic paragraphs up to the first footer paragraph.
FOOTER = re.compile(
    r"\[anzeige\]"
    r"|ältere folgen von"
    r"|sie erreichen uns"
    r"|auf instagram sind wir"
    r"|^hier geht"
    r"|die österreich- und schweizausgaben"
    r"|^sprachnachrichten"
    r"|^mehr hören"
    r"|digital- oder podcastabo"
    r"|podcast-abo",
    re.I,
)

TAG = re.compile(r"<[^>]+>")
BLOCK = re.compile(r"</p>|<br\s*/?>|</li>", re.I)


def clean_notes(raw: str) -> str:
    if not raw:
        return ""
    text = BLOCK.sub("\n", raw)          # block ends -> newlines
    text = TAG.sub("", text)             # strip remaining tags
    text = html.unescape(text).replace("\xa0", " ")
    paras = [re.sub(r"[ \t]+", " ", p).strip() for p in text.split("\n")]
    kept = []
    for p in paras:
        if not p:
            continue
        if FOOTER.search(p):             # footer reached -> stop
            break
        kept.append(p)
    return "\n\n".join(kept).strip()


try:
    LINKS = json.load(open(OUT / "zeit_links.json", encoding="utf-8"))
except FileNotFoundError:
    LINKS = {}


def resolve_link(dstr, fallback):
    """Offiziellen zeit.de-Artikel-Link per Datum (±3 Tage) finden, sonst fallback."""
    if not LINKS:
        return fallback
    t = datetime.date.fromisoformat(dstr)
    for off in (0, -1, 1, -2, 2, -3, 3):
        k = (t + datetime.timedelta(days=off)).isoformat()
        if k in LINKS:
            return LINKS[k][0][0]
    return fallback


def main():
    if not DB.exists():
        sys.exit(f"backup not found: {DB}")
    con = sqlite3.connect(DB)
    fid = con.execute(
        "SELECT id FROM Feeds WHERE download_url=? OR title LIKE '%Servus%'",
        (FEED_URL,),
    ).fetchone()
    if not fid:
        sys.exit("SGH feed not found in backup")
    fid = fid[0]

    rows = con.execute(
        """SELECT fi.title, fi.description, fi.pubDate, fi.link, m.duration
           FROM FeedItems fi LEFT JOIN FeedMedia m ON m.feeditem = fi.id
           WHERE fi.feed = ? ORDER BY fi.pubDate ASC""",
        (fid,),
    ).fetchall()

    episodes = []
    for nr, (title, desc, pub, link, dur) in enumerate(rows, start=1):
        date = datetime.datetime.fromtimestamp(pub / 1000, datetime.UTC).date()
        episodes.append({
            "nr": nr,
            "date": date.isoformat(),
            "year": date.year,
            "title": (title or "").strip(),
            "notes": clean_notes(desc),
            "duration_min": round(dur / 60000) if dur else None,
            "link": resolve_link(date.isoformat(), (link or "").strip()),
        })

    # JSON
    (OUT / "sgh-episodes.json").write_text(
        json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV
    with (OUT / "sgh-episodes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["nr", "date", "year", "title",
                                          "duration_min", "notes", "link"])
        w.writeheader()
        for e in episodes:
            w.writerow({k: e[k] for k in w.fieldnames})

    # HTML site for GitHub Pages (data embedded; "</" escaped so it can't close <script>)
    payload = json.dumps(episodes, ensure_ascii=False).replace("</", "<\\/")
    docs = OUT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text(
        HTML_TEMPLATE.replace("__DATA__", payload), encoding="utf-8")

    yrs = sorted({e["year"] for e in episodes})
    print(f"{len(episodes)} Folgen  {episodes[0]['date']} … {episodes[-1]['date']}"
          f"  ({yrs[0]}–{yrs[-1]})")
    print("→ sgh-episodes.json, sgh-episodes.csv, docs/index.html")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Servus. Grüezi. Hallo. — Folgen-Index</title>
<style>
  :root{--bg:#fafaf8;--card:#fff;--ink:#1c1c1c;--mut:#6b6b6b;--line:#e6e3dc;
        --accent:#b00;--mark:#ffe58a}
  *{box-sizing:border-box}
  body{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       color:var(--ink);background:var(--bg)}
  header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
         padding:14px 18px;z-index:5}
  h1{margin:0 0 2px;font-size:19px}
  h1 span{color:var(--accent)}
  .sub{color:var(--mut);font-size:13px;margin-bottom:10px}
  .notice{margin:0 0 10px;padding:7px 11px;font-size:12.5px;line-height:1.5;
          background:#fff7e6;border:1px solid #f0d9a0;border-left:3px solid #d98a00;
          border-radius:6px;color:#5a4500}
  .notice a{color:var(--accent)}
  .controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  #q{flex:1 1 260px;min-width:200px;padding:9px 12px;font-size:15px;
     border:1px solid var(--line);border-radius:8px;background:var(--card)}
  select,button{padding:9px 10px;font-size:14px;border:1px solid var(--line);
                border-radius:8px;background:var(--card);color:var(--ink);cursor:pointer}
  #count{color:var(--mut);font-size:13px;margin-left:auto}
  main{max-width:860px;margin:0 auto;padding:14px 18px 60px}
  .ep{background:var(--card);border:1px solid var(--line);border-radius:10px;
      padding:12px 14px;margin:10px 0}
  .ep .meta{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;
            font-size:13px;color:var(--mut)}
  .ep .nr{font-variant-numeric:tabular-nums}
  .ep .date{font-weight:600;color:var(--ink)}
  .ep h2{margin:3px 0 6px;font-size:17px;line-height:1.3}
  .notes{white-space:pre-wrap;color:#333;font-size:14.5px;
         max-height:5.4em;overflow:hidden;position:relative}
  .ep.open .notes{max-height:none}
  .notes.clip::after{content:"";position:absolute;left:0;right:0;bottom:0;height:1.6em;
         background:linear-gradient(transparent,var(--card))}
  .more{margin-top:4px;background:none;border:0;color:var(--accent);
        padding:2px 0;font-size:13px;cursor:pointer}
  mark{background:var(--mark);padding:0 1px;border-radius:2px}
  a.zeit{color:var(--accent);text-decoration:none;font-size:13px}
  .empty{color:var(--mut);text-align:center;padding:40px}
  footer{max-width:860px;margin:0 auto;padding:20px 18px 50px;color:var(--mut);
         font-size:12px;line-height:1.7;border-top:1px solid var(--line)}
  footer a{color:var(--accent);text-decoration:none}
</style>
</head>
<body>
<header>
  <h1><span>Servus.</span> <span>Grüezi.</span> <span>Hallo.</span> — Folgen-Index</h1>
  <div class="sub" id="sub"></div>
  <div class="notice"><strong>Inoffizielles Fan-Projekt</strong> – kein Angebot von DIE ZEIT. Titel und Beschreibungen © DIE ZEIT; jede Folge verlinkt auf die offizielle Episode bei <a href="https://www.zeit.de/serie/servus-gruezi-hallo" target="_blank" rel="noopener">zeit.de</a>.</div>
  <div class="controls">
    <input id="q" type="search" placeholder="Volltextsuche in Titel &amp; Themen … (z. B. Deepfake, Wahl, Gesundheit)" autofocus>
    <select id="year"><option value="">Alle Jahre</option></select>
    <select id="sort">
      <option value="desc">Neueste zuerst</option>
      <option value="asc">Älteste zuerst</option>
    </select>
    <span id="count"></span>
  </div>
</header>
<main id="list"></main>
<footer>
  Inoffizielles, nicht-kommerzielles Fan-Projekt – <strong>kein offizielles Angebot von DIE ZEIT</strong>.
  Titel und Beschreibungen © DIE ZEIT; jede Folge verlinkt auf die offizielle Episode bei
  <a href="https://www.zeit.de/serie/servus-gruezi-hallo" target="_blank" rel="noopener">zeit.de</a>.
  Der Podcast »Servus. Grüezi. Hallo.« erscheint bei ZEIT ONLINE. Daten aus öffentlich
  abrufbaren Folgeninformationen.
</footer>

<script>
const EPISODES = __DATA__;
const norm = s => (s||"").toLowerCase()
  .normalize("NFD").replace(/[̀-ͯ]/g,"")
  .replace(/ß/g,"ss").replace(/ä/g,"a").replace(/ö/g,"o").replace(/ü/g,"u");
EPISODES.forEach(e => e._h = norm(e.title + " " + e.notes));

const $ = id => document.getElementById(id);
const list=$("list"), q=$("q"), yearSel=$("year"), sortSel=$("sort");

const years=[...new Set(EPISODES.map(e=>e.year))].sort((a,b)=>b-a);
years.forEach(y=>{const o=document.createElement("option");o.value=y;o.textContent=y;yearSel.appendChild(o)});
$("sub").textContent = EPISODES.length+" Folgen · "+EPISODES[0].date+" bis "+EPISODES[EPISODES.length-1].date;

function esc(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
function tokens(query){return norm(query).split(/\s+/).filter(Boolean)}
function highlight(text, toks){
  let out=esc(text);
  if(!toks.length) return out;
  // match on a normalized copy, map back by splitting on word chars
  const re=new RegExp("("+toks.map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")).join("|")+")","gi");
  // naive highlight: works on raw text for ascii-ish terms
  return out.replace(re, m=>"<mark>"+m+"</mark>");
}

function render(){
  const toks=tokens(q.value), yr=yearSel.value, dir=sortSel.value;
  let items=EPISODES.filter(e=>{
    if(yr && String(e.year)!==yr) return false;
    return toks.every(t=>e._h.includes(t));
  });
  items.sort((a,b)=> dir==="asc" ? a.nr-b.nr : b.nr-a.nr);
  $("count").textContent = items.length+" Treffer";
  if(!items.length){ list.innerHTML='<div class="empty">Keine Folge gefunden.</div>'; return; }
  list.innerHTML="";
  for(const e of items){
    const div=document.createElement("div"); div.className="ep";
    const dur=e.duration_min?(" · "+e.duration_min+" min"):"";
    div.innerHTML =
      '<div class="meta"><span class="nr">#'+e.nr+'</span>'
      +'<span class="date">'+e.date+'</span><span>'+dur+'</span>'
      +(e.link?' · <a class="zeit" href="'+e.link+'" target="_blank" rel="noopener">zeit.de ↗</a>':'')
      +'</div>'
      +'<h2>'+highlight(e.title,toks)+'</h2>'
      +'<div class="notes">'+highlight(e.notes,toks)+'</div>';
    list.appendChild(div);
    const notes=div.querySelector(".notes");
    if(notes.scrollHeight > notes.clientHeight + 4){
      notes.classList.add("clip");
      const b=document.createElement("button"); b.className="more"; b.textContent="mehr anzeigen";
      b.onclick=()=>{const op=div.classList.toggle("open");notes.classList.toggle("clip",!op);
                     b.textContent=op?"weniger":"mehr anzeigen"};
      div.appendChild(b);
    }
  }
}
let t; q.addEventListener("input",()=>{clearTimeout(t);t=setTimeout(render,120)});
yearSel.addEventListener("change",render);
sortSel.addEventListener("change",render);
render();
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()
