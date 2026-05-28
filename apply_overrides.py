#!/usr/bin/env python3
"""Menschliche Korrekturen als finale Autoritaet ueber den Auto-Output legen.

Liest den Auto-Output ({prefix}_final.json) und eine Overrides-Datei
({"mm:ss": "Name", ...}) und schreibt eine verifizierte Fassung. Braucht keine
Embeddings -> der iterative Review-Schritt ist billig.

Optional: wird die urspruengliche diarized.json mitgegeben, wird die
Sprecher-Genauigkeit roh(whisperX) vs. Pipeline vs. Gold berechnet.

Usage:
  python3 apply_overrides.py <final.json> <overrides.json> <out_prefix> [diarized.json]
"""
import json, sys

MAPPING = {"SPEAKER_03": "Lenz Jacobsen", "SPEAKER_02": "Florian Gasser",
           "SPEAKER_01": "Matthias Daum", "SPEAKER_00": "Monika Pielert"}

def mmss(t): t = int(t or 0); return f"{t//60:02d}:{t%60:02d}"
def srt_ts(t):
    ms = int(round((t or 0)*1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def main():
    rows = json.load(open(sys.argv[1], encoding="utf-8"))
    ov = json.load(open(sys.argv[2], encoding="utf-8"))
    prefix = sys.argv[3]
    n_change = n_confirm = 0
    for r in rows:
        key = mmss(r["start"])
        if key in ov:
            new = ov[key]
            if new != r["name"]:
                r["marker"] = f"✓ manuell (war {r['name']})"; r["name"] = new; n_change += 1
            else:
                r["marker"] = "✓ bestätigt"; n_confirm += 1
    txt = [f"[{mmss(r['start'])}] {r['name']}: {r['text']}" + (f"   {r['marker']}" if r["marker"] else "") for r in rows]
    srt = [f"{k}\n{srt_ts(r['start'])} --> {srt_ts(r['end'])}\n{r['name']}: {r['text']}\n" for k, r in enumerate(rows, 1)]
    open(f"{prefix}_verified.txt", "w", encoding="utf-8").write("\n".join(txt) + "\n")
    open(f"{prefix}_verified.srt", "w", encoding="utf-8").write("\n".join(srt) + "\n")
    json.dump(rows, open(f"{prefix}_verified.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{n_change} korrigiert, {n_confirm} bestätigt -> {prefix}_verified.*")

    if len(sys.argv) > 4:
        segs = json.load(open(sys.argv[4], encoding="utf-8"))["segments"]
        if len(segs) == len(rows):
            gold = [r["name"] for r in rows]
            raw = [MAPPING.get(s.get("speaker"), s.get("speaker")) for s in segs]
            pipe = json.load(open(sys.argv[1], encoding="utf-8"))  # Pipeline VOR Overrides
            pipe = [r["name"] for r in pipe]
            acc = lambda a: 100 * sum(x == y for x, y in zip(a, gold)) / len(gold)
            print(f"\nSprecher-Genauigkeit (n={len(gold)} Segmente, Gold = dein Review):")
            print(f"  roh (whisperX-Diarisierung): {acc(raw):.1f}%")
            print(f"  Auto-Pipeline:               {acc(pipe):.1f}%")
            print(f"  verifiziert:                 100.0%")
        else:
            print(f"(Genauigkeit übersprungen: {len(segs)} Segmente vs {len(rows)} Zeilen)")

if __name__ == "__main__":
    main()
