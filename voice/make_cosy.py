"""Chinese words for the 4G speaker said by Fun-CosyVoice3-0.5B (Jesse, 2026-11-09: the Kokoro and MeloTTS words had
wrong tones and vowels: 零 as a fourth tone, 五 not third, 八 as "bai").

  python voice/make_cosy.py <out_dir>     (CosyVoice checked out in ./CosyVoice, the model in ./CosyVoice/pretrained_models)

Each word is said on its own, zero-shot from a prompt voice: out/<prompt>/<piece>.wav (16 kHz mono) and report.json.
Prompts: "melo" = the MeloTTS sentence the Wi-Fi speakers play for 1,000 (the voice Jesse chose on PB0002),
"cv" = CosyVoice's own example prompt. The pieces have the names of make_4g_clips.py (head, tail, n/<n>, t/<n>,
h/<d>, k/<d>, ling, wan), so the server's zh4p layout takes them as they are.
"""
import json, os, sys, time
sys.path.insert(0, "CosyVoice")
sys.path.insert(0, "CosyVoice/third_party/Matcha-TTS")
import numpy as np
import soundfile as sf
import torch, torchaudio
from cosyvoice.cli.cosyvoice import AutoModel

HERE = os.path.dirname(os.path.abspath(__file__))
DIGITS = "零一二三四五六七八九"
PROMPTS = {
    "melo": (os.path.join(HERE, "prompts/melo-1000.wav"), "已到账一千先令。"),
    "cv": ("CosyVoice/asset/zero_shot_prompt.wav", "希望你以后能够做的比我还好呦。"),
}
ONLY = [p for p in os.environ.get("PROMPTS", "melo,cv").split(",") if p]
SYSTEM = "You are a helpful assistant.<|endofprompt|>"


def section(n):
    if n == 2:
        return "两"
    t, u = divmod(n, 10)
    return ("" if t == 0 else ("十" if t == 1 else DIGITS[t] + "十")) + ("" if u == 0 else DIGITS[u])


def words():
    w = [("head", "已到账"), ("tail", "先令"), ("ling", "零"), ("wan", "万"), ("er", "二")]
    w += [(f"b/{c}", c) for c in "一三四五六七八九十百千"]  # single characters, for Jesse to check first
    w += [(f"n/{n}", section(n)) for n in range(1, 100)]
    w += [(f"t/{n}", "一十" + ("" if n == 10 else DIGITS[n - 10])) for n in range(10, 20)]
    w += [(f"h/{d}", ("两" if d == 2 else DIGITS[d]) + "百") for d in range(1, 10)]
    w += [(f"k/{d}", ("两" if d == 2 else DIGITS[d]) + "千") for d in range(1, 10)]
    return w


def basic():
    """The base words Jesse checks first: 0-9, 两, 十 百 千 万, 已到账, 先令."""
    keep = {"head", "tail", "ling", "wan", "er", "n/2"} | {f"b/{c}" for c in "一三四五六七八九十百千"}
    return [(n, w) for n, w in words() if n in keep]


def main(out):
    model = AutoModel(model_dir="CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B")
    sr = model.sample_rate
    rp = os.path.join(out, "report.json")
    report = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else []
    for p in ONLY:
        wav, text = PROMPTS[p]
        for name, word in (basic() if os.environ.get("SET") == "basic" else words()):
            path = os.path.join(out, p, name + ".wav")
            if os.path.exists(path):  # made before a crash: the workflow runs this again until all are there
                continue
            t0 = time.time()
            chunks = [j["tts_speech"] for j in model.inference_zero_shot(word + "。", SYSTEM + text, wav, stream=False)]
            speech = torchaudio.functional.resample(torch.cat(chunks, dim=1), sr, 16000)
            x = speech[0].numpy()
            loud = np.where(np.abs(x) > 0.02 * np.abs(x).max())[0]
            x = x[max(0, loud[0] - 320): loud[-1] + 800]
            x = x / max(np.abs(x).max(), 1e-6) * 0.8
            os.makedirs(os.path.dirname(path), exist_ok=True)
            sf.write(path, x.astype(np.float32), 16000, subtype="PCM_16")
            row = {"prompt": p, "piece": name, "word": word, "seconds": round(len(x) / 16000, 3),
                   "took": round(time.time() - t0, 1)}
            report.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:  # kept as it goes, for a timeout
                json.dump(report, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
