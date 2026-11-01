"""Make PesaBell's Chinese voice pack "zh-a": every announcement part as one whole sentence, as MP3.

  VERSION=<k> python make_zh_a.py <shard> <shards> <out_dir>    (models in ./models, see .github/workflows/voice.yml)

Version 3 (used): version 2 with the sentences listed in voice/fix.json made again (.github/workflows/voice-fix.yml).
Version 2: s/1-99,999, whole sentences only; it makes 10,000-99,999 and the sentences version 1 never got
heard right (RETRY, from version 1's report.json), the workflow takes the rest of version 1. Version 1's parts for
"一万" + "两千五百先令" (w/, y/, z/ below) are not used by the server: a part that starts with a number slurs it.

Voice: MeloTTS Chinese (MIT, the sherpa-onnx export vits-melo-tts-zh_en), chosen by ear by Jesse on PB0002
(2026-10-31) over word clips joined end to end. Each part is said in one go, so the tones and the rhythm are those
of a sentence. The voice is a little different every time, and sometimes slurs a word; so each part is made up to
six times and a speech recognizer (sherpa-onnx paraformer zh) checks it: the first take whose words come back
right is kept (the tone of 先令 is not checked: the recognizer hears it as 限令 even when it sounds right).

The server (pesabell-server, src/speaker/voice.js) plays chime.mp3 and then the parts of an amount, as one MP3:
  s/<n>.mp3    1-9,999:            已到账<n>先令
  wx/<x>.mp3   x万 exactly:        已到账<x>万先令            (x = 1-99)
  w/<x>.mp3    and then ...         已到账<x>万，
  y/<y>.mp3      the rest >= 1,000:   <y>先令                  (y = 1,000-9,999)
  z/<y>.mp3      the rest < 1,000:    零<y>先令                (y = 1-999)
MP3: MPEG-2 layer III, 16 kHz mono 16 kbps, no bit reservoir and no headers, so parts join by putting one
after the other (the speakers' format). chime.mp3 is voice/033.wav, the English "PesaBell!" with its chime.
"""
import difflib, json, os, subprocess, sys, time, wave

import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")
DIGITS = "零一二三四五六七八九"
TAKES = {1: 6, 2: 10, 3: 20}


def section(n, lead=True, alone=True):
    """1-9,999 in Chinese characters: 两千/两百, 十二 at the start of a number (一十二 after 百), 零 for gaps."""
    digits = [n // 1000, n // 100 % 10, n // 10 % 10, n % 10]
    units = ["千", "百", "十", ""]
    out, zero, started = "", False, False
    for i, d in enumerate(digits):
        if d == 0:
            zero = zero or started
            continue
        if zero:
            out, zero = out + "零", False
        if i == 2 and d == 1 and lead and not started:
            word = ""
        elif d == 2 and (i < 2 or (i == 3 and alone and n == 2)):
            word = "两"
        else:
            word = DIGITS[d]
        out += word + units[i]
        started = True
    return out


def amount(n):
    """1-99,999 in Chinese characters: 一万两千五百, 一万零五, 两万."""
    if n < 10000:
        return section(n)
    x, y = divmod(n, 10000)
    rest = "" if not y else section(y, lead=False) if y >= 1000 else "零" + section(y, lead=False, alone=False)
    return section(x) + "万" + rest


def items(version=1, retry=()):
    """(part, text to say, words the recognizer must hear)."""
    if version >= 3:  # remake only these, checking the amount itself: (part, [(text, speed), ...], amount in words)
        return [(f"s/{n}", [(f"已到账{amount(n)}先令。", 1.0), (f"已到账，{amount(n)}先令。", 0.9)], amount(n))
                for n in retry]
    if version >= 2:
        todo = list(retry) + list(range(10000, 100000))
        return [(f"s/{n}", f"已到账{amount(n)}先令。", f"已到账{amount(n)}") for n in todo]
    out = []
    for n in range(1, 10000):
        out.append((f"s/{n}", f"已到账{section(n)}先令。", f"已到账{section(n)}"))
    for x in range(1, 100):
        out.append((f"wx/{x}", f"已到账{section(x)}万先令。", f"已到账{section(x)}万"))
        out.append((f"w/{x}", f"已到账{section(x)}万，", f"已到账{section(x)}万"))
    for y in range(1000, 10000):
        out.append((f"y/{y}", f"{section(y, lead=False)}先令。", section(y, lead=False)))
    for y in range(1, 1000):
        words = "零" + section(y, lead=False, alone=False)
        out.append((f"z/{y}", f"{words}先令。", words))
    return out


def same(a):
    return a.replace("两", "二")


def engines(threads):
    m = os.path.join(MODELS, "vits-melo-tts-zh_en")
    tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=f"{m}/model.onnx", lexicon=f"{m}/lexicon.txt",
                                                   tokens=f"{m}/tokens.txt", dict_dir=f"{m}/dict"),
        num_threads=threads)))
    a = os.path.join(MODELS, "sherpa-onnx-paraformer-zh-small-2024-03-09")
    asr = sherpa_onnx.OfflineRecognizer.from_paraformer(paraformer=f"{a}/model.int8.onnx", tokens=f"{a}/tokens.txt",
                                                        num_threads=threads)
    return tts, asr


def to16k(samples, rate):
    x = np.asarray(samples, dtype=np.float32)
    if rate == 44100:
        return resample_poly(x, 160, 441).astype(np.float32)
    if rate == 24000:
        return resample_poly(x, 2, 3).astype(np.float32)
    if rate == 22050:
        return resample_poly(x, 320, 441).astype(np.float32)
    assert rate == 16000, rate
    return x


def tidy(x):
    """30 ms before the first sound, 80 ms after the last, loudest sample at 0.8."""
    loud = np.where(np.abs(x) > 0.003)[0]
    if not len(loud):
        return x
    x = x[max(loud[0] - 480, 0): loud[-1] + 1280]
    return x * (0.8 / max(np.abs(x).max(), 1e-6))


def mp3(pcm16k, path):
    pcm = (np.clip(pcm16k, -1, 1) * 32767).astype(np.int16).tobytes()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "-",
                    "-c:a", "libmp3lame", "-b:a", "16k", "-reservoir", "0", "-write_xing", "0", "-id3v2_version", "0",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-f", "mp3", path], input=pcm, check=True)


def chime(out):
    with wave.open(os.path.join(HERE, "033.wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    loud = np.where(np.abs(x) > 0.01)[0]
    mp3(x[max(loud[0] - 160, 0): loud[-1] + 800], os.path.join(out, "chime.mp3"))


def main(shard, shards, out):
    shard, shards = int(shard), int(shards)
    version = int(os.environ.get("VERSION", "1"))
    retry = [int(n) for n in os.environ.get("RETRY", "").split()]
    tts, asr = engines(int(os.environ.get("THREADS", "4")))
    todo = items(version, retry)[shard::shards]
    report = []
    started = time.time()
    for k, (part, text, want) in enumerate(todo):
        path = os.path.join(out, part + ".mp3")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        best = None
        # Version 3 tries the plain sentence first, then with a short pause after 已到账, said a little slower
        # (60,120 almost never came out right otherwise); it checks the amount itself and 到账.
        variants = text if isinstance(text, list) else [(text, 1.0)]
        take = 0
        for say, speed in variants:
            for _ in range(TAKES[version]):
                take += 1
                a = tts.generate(say, sid=0, speed=speed)
                x = to16k(a.samples, a.sample_rate)
                s = asr.create_stream()
                s.accept_waveform(16000, x)
                asr.decode_stream(s)
                heard = s.result.text
                if version >= 3:
                    ok = same(want) in same(heard) and "到账" in heard
                else:
                    ok = same(want) in same(heard) and same(heard).startswith(same(want)[:3])
                score = difflib.SequenceMatcher(None, same(heard), same(want)).ratio() + (1 if ok else 0)
                if best is None or score > best[0]:
                    best = (score, x, heard, take, ok)
                if ok:
                    break
            if best[4]:
                break
        _, x, heard, take, ok = best
        mp3(tidy(x), path)
        report.append({"part": part, "takes": take, "ok": ok, "heard": heard})
        if k % 100 == 0:
            print(f"shard {shard}: {k}/{len(todo)} in {time.time() - started:.0f} s", flush=True)
    if shard == 0 and version == 1:
        chime(out)
    with open(os.path.join(out, f"report-{shard}.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False)
    bad = [r for r in report if not r["ok"]]
    print(f"shard {shard}: {len(report)} parts, {len(bad)} never heard right, {time.time() - started:.0f} s")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--list"]:
        for part, text, want in items(int(os.environ.get("VERSION", "1"))):
            print(part, text, want)
    else:
        main(*sys.argv[1:4])
