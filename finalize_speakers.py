#!/usr/bin/env python3
"""Finale Sprecher-Zuordnung fuer 'grobe' who-said-what (Option B + gezielter
akustischer Override + kombinierte Flags + Split nur bei langen Runs).

Pro whisperX-Segment:
  base  = dauergewichtete Wort-Mehrheit            -> behebt Fenster-Override (Art 1)
  einheitliche Segmente: akustischer Ebene-2-Override, falls klar widersprechend
                                                    -> behebt 'einheitlich falsch' (Art 2)
  gemischt + Akustik widerspricht                  -> Overlap-Flag (Label = Wort-Mehrheit)
  Split NUR bei Fremd-Run >= SPLIT_MIN_RUN Woertern; kurzes Jitter wird in die
        Mehrheit absorbiert (keine Mini-Fragmente).

Usage:
  uv run --with speechbrain --with soundfile --with numpy \
      finalize_speakers.py <16k_mono.wav> <diarized.json> <out_prefix>
"""
import json, sys, math, itertools
import numpy as np, torch, soundfile as sf
from speechbrain.inference.speaker import EncoderClassifier

MAPPING = {
    "SPEAKER_03": "Lenz Jacobsen", "SPEAKER_02": "Florian Gasser",
    "SPEAKER_01": "Matthias Daum", "SPEAKER_00": "Monika Pielert",
}
SR = 16000
T, HI, LO, AMBIG = 0.10, 0.80, 0.15, 0.60
SPLIT_MIN_RUN = 3      # Woerter; kuerzere Fremd-Runs werden absorbiert
SHORT = 0.8            # s; kuerzere Fragmente werden geflaggt

def nm(L): return MAPPING.get(L, L or "?")
def mmss(s): s = int(s or 0); return f"{s//60:02d}:{s%60:02d}"
def srt_ts(t):
    ms = int(round((t or 0) * 1000)); h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000); return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def dur_majority(words, fallback):
    dur = {}
    for w in words:
        dur[w.get("speaker")] = dur.get(w.get("speaker"), 0) + (w.get("end", 0) - w.get("start", 0))
    return max(dur, key=dur.get) if dur else fallback

def runs_of(words):
    return [(spk, list(g)) for spk, g in itertools.groupby(words, key=lambda w: w.get("speaker"))]

def main():
    wav, src, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
    audio, _ = sf.read(wav, dtype="float32")
    if audio.ndim > 1: audio = audio.mean(1)
    segs = json.load(open(src, encoding="utf-8"))["segments"]
    enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                         run_opts={"device": "cpu"})
    def embed(a, b):
        seg = audio[int(a * SR):int(b * SR)]
        if len(seg) < int(SR * 0.25): seg = np.pad(seg, (0, int(SR * 0.25) - len(seg)))
        e = enc.encode_batch(torch.tensor(seg).unsqueeze(0)).squeeze().detach().numpy()
        n = np.linalg.norm(e); return e / n if n else e

    bases, embs, wlists = [], [], []
    for s in segs:
        ws = [w for w in s.get("words", []) if "speaker" in w]
        wlists.append(ws)
        bases.append(dur_majority(ws, s.get("speaker")))
        embs.append(embed(s["start"], s["end"]))

    labels = sorted(set(bases))
    cents = {}
    for L in labels:
        idx = [i for i, s in enumerate(segs) if bases[i] == L and (s["end"] - s["start"]) >= 3.0
               and len(set(w.get("speaker") for w in wlists[i])) <= 1]
        if not idx: idx = [i for i in range(len(segs)) if bases[i] == L]
        c = np.mean([embs[i] for i in idx], axis=0); n = np.linalg.norm(c)
        cents[L] = c / n if n else c

    def emit(rows, start, end, label, text, marker=""):
        rows.append({"start": start, "end": end, "label": label, "name": nm(label),
                     "text": text, "marker": marker})

    rows, n_relabel, n_split, n_flag = [], 0, 0, 0
    diag = ["=== Aenderungen/Flags ==="]
    for i, s in enumerate(segs):
        ws, base = wlists[i], bases[i]
        runs = runs_of(ws)
        distinct = set(spk for spk, _ in runs)
        mixed = len(distinct) > 1
        big = [(spk, g) for spk, g in runs if spk != base and len(g) >= SPLIT_MIN_RUN]

        # akustische Posterioren (ueber das ganze Segment)
        sims = {L: float(np.dot(embs[i], cents[L])) for L in labels}
        mx = max(sims.values()); ex = {L: math.exp((v - mx) / T) for L, v in sims.items()}
        Z = sum(ex.values()); post = {L: ex[L] / Z for L in labels}
        best = max(sims, key=sims.get)

        # Split nur, wenn ein langer Fremd-Run da ist UND die Akustik nicht ohnehin
        # klar einen Sprecher fuers ganze Segment sieht (sonst: Wort-Jitter -> base).
        if big and post[best] < HI:
            for w in ws:
                w["_lab"] = base
            for spk, g in big:
                for w in g: w["_lab"] = spk
            for lab, grp in itertools.groupby(ws, key=lambda w: w["_lab"]):
                grp = list(grp); a, b = grp[0]["start"], grp[-1]["end"]
                txt = " ".join(w.get("word", "").strip() for w in grp).strip()
                mk = "⚠ kurz" if (b - a) < SHORT else ""
                emit(rows, a, b, lab, txt, mk)
            n_split += 1
            diag.append(f"[{mmss(s['start'])}] SPLIT '{s['text'].strip()[:40]}' "
                        f"-> {[nm(l) for l in dict.fromkeys(w['_lab'] for w in ws)]}")
            continue

        label, marker = base, ""
        if not mixed and best != base and post[best] >= HI and post.get(base, 0) < LO:
            label = best; n_relabel += 1
            marker = f"✎ war {nm(base)} (akustisch {nm(best)} {post[best]*100:.0f}%)"
            diag.append(f"[{mmss(s['start'])}] RELABEL '{s['text'].strip()[:40]}' {nm(base)}->{nm(best)}")
        else:
            if mixed and best != label:
                marker = f"⚠ Overlap, evtl. {nm(best)}"
            elif post.get(label, 0) < AMBIG:
                marker = f"⚠ unsicher {post.get(label,0)*100:.0f}%"
            elif (s["end"] - s["start"]) < SHORT:
                marker = "⚠ sehr kurz"
            if marker:
                n_flag += 1
                diag.append(f"[{mmss(s['start'])}] FLAG '{s['text'].strip()[:34]}' {marker}")
        emit(rows, s["start"], s["end"], label, s["text"].strip(), marker)

    # Ausgaben
    txt = [f"[{mmss(r['start'])}] {r['name']}: {r['text']}" + (f"   {r['marker']}" if r["marker"] else "")
           for r in rows]
    srt = []
    for k, r in enumerate(rows, 1):
        sub = r["name"] + (" (?)" if r["marker"].startswith("⚠") else "")
        srt.append(f"{k}\n{srt_ts(r['start'])} --> {srt_ts(r['end'])}\n{sub}: {r['text']}\n")
    open(f"{prefix}.txt", "w", encoding="utf-8").write("\n".join(txt) + "\n")
    open(f"{prefix}.srt", "w", encoding="utf-8").write("\n".join(srt) + "\n")
    json.dump(rows, open(f"{prefix}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n".join(diag))
    print(f"\n{len(segs)} Segmente -> {len(rows)} Zeilen | {n_relabel} akustisch umgelabelt | "
          f"{n_split} gesplittet | {n_flag} markiert")

if __name__ == "__main__":
    main()
