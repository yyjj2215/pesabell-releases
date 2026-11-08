"""Make the Chinese pieces for the 4G speaker (no http audio: it joins files it holds), cut out of whole sentences.

  python make_4g_clips.py <out_dir>        (models in ./models, see .github/workflows/voice-4g.yml)

Jesse, 2026-11-08: a payment is 已到账 + the amount + 先令. Each piece is cut out of a whole sentence said by the same
MeloTTS voice as the Wi-Fi speakers' sentences (make_zh_a.py), from where it sits in a real announcement, so it keeps
the tone of the middle of a sentence (word clips said alone end each word as if the sentence stopped there). The
recognizer (sherpa-onnx paraformer zh) gives each character's start time; a piece runs from its first character's
onset to the next character's onset (boundary(): the quietest point just before the recognizer's time). A sentence is said again (up to TAKES times) until every character is heard
right and has a time.

Pieces (the server, pesabell-server src/speaker/packs.js, joins them):
  head.wav        已到账            from 已到账二十五先令
  tail.wav        先令              from 已到账二十五先令
  n/<n>.wav       1-99 as said on their own or at the start: 五, 十二, 二十五 (2: 两 alone)
  t/<n>.wav       10-19 after 百/千: 一十, 一十二
  h/<d>.wav       一百 ... 九百 (两百)
  k/<d>.wav       一千 ... 九千 (两千)
  ling.wav        零
  z/<r>.wav       零 and what follows, in one go: 零五, 零二, 零一十二, 零五十 (1-19, 20-90 by tens)
  wan.wav         万
"""
import json, os, sys, wave

import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")
DIGITS = "零一二三四五六七八九"
TAKES = 12
LEAD = 0.025  # seconds kept before a piece's first character
TAIL = 0.08   # after the last character of a sentence


def section(n):
    """1-99 said on its own: 五, 十二, 二十五; 2 alone is 两."""
    if n == 2:
        return "两"
    t, u = divmod(n, 10)
    return ("" if t == 0 else ("十" if t == 1 else DIGITS[t] + "十")) + ("" if u == 0 else DIGITS[u])


def big(d, unit):
    return ("两" if d == 2 else DIGITS[d]) + unit


def jobs():
    """(name, sentence, the piece's characters, which occurrence: 0 = first)."""
    out = [("head", "已到账二十五先令。", "已到账", 0), ("tail", "已到账二十五先令。", "先令", 0)]
    for n in range(1, 100):
        out.append((f"n/{n}", f"已到账{section(n)}先令。", section(n), 0))
    for n in range(10, 20):
        piece = "一十" + ("" if n == 10 else DIGITS[n - 10])
        out.append((f"t/{n}", f"已到账三百{piece}先令。", piece, 0))
    for d in range(1, 10):
        out.append((f"h/{d}", f"已到账{big(d, '百')}五十先令。", big(d, "百"), 0))
        out.append((f"k/{d}", f"已到账{big(d, '千')}三百先令。", big(d, "千"), 0))
    out.append(("ling", "已到账一千，零二十五先令。", "零", 0))
    # 零 with what follows it, said in one go (Jesse, 2026-11-08: 4050's 零 joined alone was not clear): 零五, 零五十, 零一十二
    for r in list(range(1, 20)) + list(range(20, 100, 10)):
        x = DIGITS[r] if r < 10 else ("一十" + ("" if r == 10 else DIGITS[r - 10]) if r < 20 else DIGITS[r // 10] + "十")
        # After a comma: 零 then starts after a pause, so its l is not run together with the n of 千 and can be cut
        # whole (the speaker plays a pause between the amount's parts anyway).
        out.append((f"z/{r}", f"已到账一千，零{x}先令。", "零" + x, 0))
    out.append(("wan", "已到账两万五千先令。", "万", 0))
    return out


# Sound-alikes the recognizer writes for a number said right (七 as 期, 十 as 时, 五 as 午): the times still fit.
ALIKE = str.maketrans({"两": "二", "期": "七", "齐": "七", "时": "十", "实": "十", "石": "十", "是": "十", "午": "五",
                       "武": "五", "舞": "五"})


def boundary(x, t, back=0.18):
    """Where a character really starts: the recognizer's time is the loud part, often tens of ms after the onset
    (零 after 千: the l runs on from the n with no gap, so a cut at the time clips it). The quietest 10 ms within
    `back` seconds before t."""
    hop, win = 80, 160
    lo = max(0, int((t - back) * 16000))
    hi = min(len(x) - win, int(t * 16000))
    if hi <= lo:
        return t
    best = min(range(lo, hi, hop), key=lambda i: float(np.mean(x[i:i + win] ** 2)))
    return (best + win // 2) / 16000


def same(a):
    return a.translate(ALIKE)


def engines():
    m = os.path.join(MODELS, "vits-melo-tts-zh_en")
    tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=f"{m}/model.onnx", lexicon=f"{m}/lexicon.txt",
                                                   tokens=f"{m}/tokens.txt", dict_dir=f"{m}/dict"),
        num_threads=4)))
    a = os.path.join(MODELS, os.environ.get("ASR", "sherpa-onnx-paraformer-zh-2023-09-14"))  # one that gives timestamps
    asr = sherpa_onnx.OfflineRecognizer.from_paraformer(paraformer=f"{a}/model.int8.onnx", tokens=f"{a}/tokens.txt",
                                                        num_threads=4)
    return tts, asr


def to16k(samples, rate):
    x = np.asarray(samples, dtype=np.float32)
    if rate == 16000:
        return x
    from math import gcd
    g = gcd(16000, rate)
    return resample_poly(x, 16000 // g, rate // g).astype(np.float32)


def write(path, x):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fade = int(0.004 * 16000)
    x = x.copy()
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    if len(pcm) % 2:  # the vendor tool's compression wants an even sample count
        pcm = np.append(pcm, np.int16(0))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())


def main(out):
    tts, asr = engines()
    report = []
    for name, sentence, piece, _ in jobs():
        want = sentence.rstrip("。").replace("，", "")
        best = None
        for take in range(1, TAKES + 1):
            a = tts.generate(sentence, sid=0, speed=1.0)
            x = to16k(a.samples, a.sample_rate)
            s = asr.create_stream()
            s.accept_waveform(16000, x)
            asr.decode_stream(s)
            heard = s.result.text.replace(" ", "")
            times = list(s.result.timestamps)
            # The recognizer often writes a sound-alike (县令 for 先令, 战 for 账): what has to be right is the
            # number itself and one time per character, so the pieces can be cut by position.
            number = want[3:-2]
            ok = len(heard) == len(want) and len(times) == len(heard) and same(heard[3:-2]) == same(number)
            score = sum(a == b for a, b in zip(same(heard), same(want))) + (100 if ok else 0)
            if best is None or score > best[5]:
                best = (x, heard, times, take, ok, score)
            if ok and same(heard) == same(want):
                break
        x, heard, times, take, ok, _ = best
        row = {"piece": name, "sentence": sentence, "heard": heard, "takes": take, "ok": ok}
        if ok:
            i = want.find(piece)  # by position in the sentence: the heard text may write a sound-alike
            j = i + len(piece)
            prev = times[i - 1] if i else 0.0
            start = max(prev + 0.03, boundary(x, times[i], min(0.18, times[i] - prev - 0.03))) if i else max(0.0, times[0] - LEAD)
            end = boundary(x, times[j], min(0.18, times[j] - max(times[j - 1], start + 0.1))) if j < len(times) else len(x) / 16000
            if j >= len(times):  # the piece ends the sentence: up to where the sound fades, plus a little
                loud = np.where(np.abs(x) > 0.01 * np.abs(x).max())[0]
                end = loud[-1] / 16000 + TAIL
            clip = x[int(start * 16000): int(end * 16000)]
            if end - start < 0.08:  # a time that makes no sense: leave the piece out, the report says so
                row.update(ok=False, why=f"times {start:.3f}-{end:.3f}")
                report.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                continue
            clip = clip * (0.8 / max(np.abs(x).max(), 1e-6))  # the sentence's loudness, not the piece's own
            write(os.path.join(out, name + ".wav"), clip)
            row.update(start=round(start, 3), end=round(end, 3))
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    bad = [r for r in report if not r["ok"]]
    print(f"{len(report)} pieces, {len(bad)} not cut: {[r['piece'] for r in bad]}")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
