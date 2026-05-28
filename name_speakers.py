#!/usr/bin/env python3
"""Relabel whisperX speaker IDs with names and emit a PER-SEGMENT transcript
with a proxy confidence flag (Ebene 1: derived from existing whisperX data, no
extra model run).

Per segment the uncertainty flag comes from:
  - word-label purity = fraction of words whose diarisation label matches the
    segment's majority speaker (mixed labels => boundary uncertainty)
  - very short duration (< MIN_DUR): short interjections are easily mislabelled
  - isolation: a different speaker than BOTH neighbours (which differ from each
    other) => likely a backchannel swallowed/placed wrong

These catch boundary/short-turn errors. They do NOT catch "confidently wrong"
uniform mislabels (e.g. a whole question assigned to the wrong person) — that
needs acoustic posteriors / embeddings (Ebene 2).

Usage: python3 name_speakers.py <diarized.json> <out.txt>
The SPEAKER_xx -> name mapping is episode-local; edit per episode.
"""
import json, sys, collections

MAPPING = {
    "SPEAKER_03": "Lenz Jacobsen",      # moderiert
    "SPEAKER_02": "Florian Gasser",     # AT
    "SPEAKER_01": "Matthias Daum",      # CH
    "SPEAKER_00": "Monika Pielert (Werbung)",
}
MIN_DUR = 0.8  # s; Turns kürzer als das sind fehleranfällig

def mmss(sec):
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"

def assess(seg, prev_spk, next_spk):
    words = seg.get("words", [])
    counts = collections.Counter(w.get("speaker") for w in words if "speaker" in w)
    tot = sum(counts.values())
    purity = (counts.most_common(1)[0][1] / tot) if tot else 1.0
    dur = seg["end"] - seg["start"]
    spk = seg.get("speaker")
    reasons = []
    if purity < 1.0:
        reasons.append(f"gemischte Labels {purity:.2f}")
    if dur < MIN_DUR:
        reasons.append(f"sehr kurz {dur:.2f}s")
    if prev_spk and next_spk and spk != prev_spk and spk != next_spk and prev_spk != next_spk:
        reasons.append("isoliert zw. zwei anderen")
    return reasons

def main():
    src, out = sys.argv[1], sys.argv[2]
    segs = json.load(open(src, encoding="utf-8"))["segments"]
    lines, nflag = [], 0
    for i, s in enumerate(segs):
        prev_spk = segs[i - 1].get("speaker") if i > 0 else None
        next_spk = segs[i + 1].get("speaker") if i + 1 < len(segs) else None
        reasons = assess(s, prev_spk, next_spk)
        name = MAPPING.get(s.get("speaker"), s.get("speaker") or "?")
        text = (s.get("text") or "").strip()
        line = f"[{mmss(s['start'])}] {name}: {text}"
        if reasons:
            line += "   ⚠ " + ", ".join(reasons)
            nflag += 1
        lines.append(line)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"{len(segs)} Segmente, {nflag} mit ⚠-Flag -> {out}")

if __name__ == "__main__":
    main()
