#!/usr/bin/env python3
"""Ebene 2 + 3: akustische Sprecher-Konfidenz und konservatives Auto-Umlabeln.

Pro whisperX-Segment:
  - ECAPA-Embedding (L2-normalisiert)
  - Zentroid je Sprecher aus dessen langen (>=3 s) Segmenten
  - Cosinus-Aehnlichkeit -> Softmax(T) -> Posterior
      konf = post[zugewiesen],  acoustic_best = argmax sim,  z = post[best]

Politik (konservativ):
  - RELABEL  : best != zugewiesen  und  post[best] >= HI  und  post[assigned] < LO
  - AMBIG    : sonst, falls post[assigned] < AMBIG  -> Label behalten, markieren
  - KEEP     : sonst

Schreibt:
  {prefix}_conf.txt        Konfidenz je Zeile (Diagnose)
  {prefix}_corrected.txt    korrigiertes Transkript mit ✎/⚠-Markern
  {prefix}_corrected.srt    korrigierte, benannte Untertitel
  {prefix}_corrected.json   Segmente mit korrigiertem Label + Status

Usage:
  uv run --with speechbrain --with soundfile --with numpy \
      confidence_check.py <16k_mono.wav> <diarized.json> <out_prefix>
"""
import json, sys, math
import numpy as np
import torch, soundfile as sf
from speechbrain.inference.speaker import EncoderClassifier

MAPPING = {
    "SPEAKER_03": "Lenz Jacobsen", "SPEAKER_02": "Florian Gasser",
    "SPEAKER_01": "Matthias Daum", "SPEAKER_00": "Monika Pielert",
}
SR = 16000
T = 0.10           # Softmax-Temperatur
HI = 0.80          # Favorit muss so sicher sein, um umzulabeln
LO = 0.15          # zugewiesene Konfidenz muss darunter liegen
AMBIG = 0.60       # darunter (aber nicht umgelabelt) -> als unsicher markieren

def mmss(s):
    s = int(s or 0); return f"{s // 60:02d}:{s % 60:02d}"

def srt_ts(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def main():
    wav_path, json_path, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
    audio, _ = sf.read(wav_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(1)
    segs = json.load(open(json_path, encoding="utf-8"))["segments"]
    enc = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cpu"})

    def embed(a, b):
        seg = audio[int(a * SR):int(b * SR)]
        if len(seg) < int(SR * 0.25):
            seg = np.pad(seg, (0, int(SR * 0.25) - len(seg)))
        e = enc.encode_batch(torch.tensor(seg).unsqueeze(0)).squeeze().detach().numpy()
        n = np.linalg.norm(e); return e / n if n else e

    embs = [embed(s["start"], s["end"]) for s in segs]
    spk = [s.get("speaker") for s in segs]
    labels = sorted(set(spk))
    cents = {}
    for L in labels:
        idx = [i for i, s in enumerate(segs) if spk[i] == L and (s["end"] - s["start"]) >= 3.0]
        if not idx:
            idx = [i for i in range(len(segs)) if spk[i] == L]
        c = np.mean([embs[i] for i in idx], axis=0); n = np.linalg.norm(c)
        cents[L] = c / n if n else c

    conf_lines, corr_lines, srt_lines, out_json = [], [], [], []
    n_relabel = n_ambig = 0
    print("=== Diagnose geaenderter/unsicherer Segmente (Roh-Cosinus) ===")
    for k, s in enumerate(segs):
        sims = {L: float(np.dot(embs[k], cents[L])) for L in labels}
        mx = max(sims.values())
        exp = {L: math.exp((v - mx) / T) for L, v in sims.items()}
        Z = sum(exp.values()); post = {L: exp[L] / Z for L in labels}
        assigned = spk[k]; best = max(sims, key=sims.get)
        conf, pbest = post.get(assigned, 0.0), post[best]
        text = (s.get("text") or "").strip()

        conf_lines.append(f"[{mmss(s['start'])}] {MAPPING.get(assigned, assigned)}: {text}"
                          f"   konf {conf*100:.0f}%"
                          + (f"  ⚠ klingt nach {MAPPING.get(best, best)} ({pbest*100:.0f}%)"
                             if best != assigned else (f"  ⚠ unsicher" if conf < AMBIG else "")))

        status, final = "keep", assigned
        if best != assigned and pbest >= HI and conf < LO:
            status, final = "relabel", best; n_relabel += 1
        elif conf < AMBIG:
            status = "ambig"; n_ambig += 1

        name = MAPPING.get(final, final)
        if status in ("relabel", "ambig"):
            sa, sb = sims[assigned], sims[best]
            print(f"[{mmss(s['start'])}] {status:7} '{text[:34]}'  "
                  f"cos: {MAPPING.get(assigned,assigned).split()[0]}={sa:.2f} "
                  f"{MAPPING.get(best,best).split()[0]}={sb:.2f}  -> {name}")

        if status == "relabel":
            corr_lines.append(f"[{mmss(s['start'])}] {name}: {text}   ✎ war {MAPPING.get(assigned, assigned)} "
                              f"(klang zu {pbest*100:.0f}% nach {name})")
            srt_name = name
        elif status == "ambig":
            corr_lines.append(f"[{mmss(s['start'])}] {name}: {text}   ⚠ unsicher (konf {conf*100:.0f}%"
                              + (f", evtl. {MAPPING.get(best, best)}" if best != assigned else "") + ")")
            srt_name = name + " (?)"
        else:
            corr_lines.append(f"[{mmss(s['start'])}] {name}: {text}")
            srt_name = name

        srt_lines.append(f"{k+1}\n{srt_ts(s['start'])} --> {srt_ts(s['end'])}\n{srt_name}: {text}\n")
        out_json.append({"start": s["start"], "end": s["end"], "text": text,
                         "speaker": final, "name": name, "conf": round(conf, 3), "status": status})

    open(f"{prefix}_conf.txt", "w", encoding="utf-8").write("\n".join(conf_lines) + "\n")
    open(f"{prefix}_corrected.txt", "w", encoding="utf-8").write("\n".join(corr_lines) + "\n")
    open(f"{prefix}_corrected.srt", "w", encoding="utf-8").write("\n".join(srt_lines) + "\n")
    json.dump(out_json, open(f"{prefix}_corrected.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n{len(segs)} Segmente | {n_relabel} umgelabelt | {n_ambig} unsicher markiert | "
          f"{len(segs)-n_relabel-n_ambig} unveraendert")

if __name__ == "__main__":
    main()
