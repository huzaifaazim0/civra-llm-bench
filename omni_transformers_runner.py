#!/usr/bin/env python3
"""Offline Qwen2.5-Omni-3B A→T metrics + A→A listen gallery (transformers)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch


def load_audio(path: Path, sr: int = 16000) -> np.ndarray:
    audio, file_sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if file_sr != sr:
        n = int(len(audio) * sr / file_sr)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(
            np.float32
        )
    return audio


def write_wav(path: Path, audio: np.ndarray, sr: int = 24000) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    sf.write(str(path), audio, sr)
    return float(len(audio) / sr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Omni-3B")
    ap.add_argument("--fixtures-dir", default="/root/.cvr/llm_stress_test/gpu/fixtures")
    ap.add_argument("--gallery-dir", default="/root/.cvr/llm_stress_test/gpu/omni_listen_gallery")
    ap.add_argument("--output", required=True)
    ap.add_argument("--mode", choices=["audio_to_text", "gallery", "both"], default="gallery")
    ap.add_argument("--max-new-tokens", type=int, default=96)
    ap.add_argument("--at-concurrency-sims", default="1,2,4")
    args = ap.parse_args()

    from transformers import Qwen2_5OmniForConditionalGeneration, Qwen2_5OmniProcessor

    print("Loading model...", flush=True)
    t0 = time.perf_counter()
    model = Qwen2_5OmniForConditionalGeneration.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    ).to("cuda")
    processor = Qwen2_5OmniProcessor.from_pretrained(args.model, trust_remote_code=True)
    load_s = time.perf_counter() - t0
    print(f"Loaded in {load_s:.1f}s", flush=True)

    fixtures_dir = Path(args.fixtures_dir)
    gallery_dir = Path(args.gallery_dir)
    gallery_dir.mkdir(parents=True, exist_ok=True)

    prefer = [
        "greeting",
        "medicare_explain",
        "clarify_zip",
        "empathy",
        "repeat_back",
        "longform",
        "rephrase_short",
        "status_update",
    ]
    by = {p.stem.removeprefix("in_"): p for p in sorted(fixtures_dir.glob("in_*.wav"))}
    fixtures = [(lab, by[lab]) for lab in prefer if lab in by]
    for lab, p in by.items():
        if lab not in {x[0] for x in fixtures}:
            fixtures.append((lab, p))

    instruction = (
        "You are a clear, warm phone agent. Listen to the caller and reply helpfully and concisely."
    )

    results: dict = {
        "engine": "transformers",
        "model": args.model,
        "load_sec": round(load_s, 2),
        "audio_to_text": [],
        "gallery": [],
        "note": (
            "vLLM-Omni default deploy needs 2 GPUs; on this 1x20GB box we use transformers. "
            "A→T concurrency sims are sequential (one model copy)."
        ),
    }

    def run_one(label: str, wav: Path, return_audio: bool):
        audio = load_audio(wav)
        conversation = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": "You are Qwen, a virtual human capable of perceiving auditory inputs.",
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio": audio},
                    {"type": "text", "text": instruction},
                ],
            },
        ]
        text = processor.apply_chat_template(conversation, add_generation_prompt=True, tokenize=False)
        inputs = processor(text=text, audio=[audio], return_tensors="pt", padding=True)
        inputs = {k: v.to("cuda") if isinstance(v, torch.Tensor) else v for k, v in inputs.items()}
        t1 = time.perf_counter()
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                return_audio=return_audio,
            )
        wall = time.perf_counter() - t1
        text_out = None
        audio_out = None
        if isinstance(out, tuple):
            text_out = processor.batch_decode(
                out[0], skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]
            audio_out = out[1] if len(out) > 1 else None
        else:
            text_out = processor.batch_decode(
                out, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]
        # strip prompt echo if present
        if text_out and "assistant" in text_out:
            text_out = text_out.split("assistant")[-1].strip()
        return wall, text_out, audio_out

    if args.mode in ("audio_to_text", "both"):
        for n in [int(x) for x in args.at_concurrency_sims.split(",") if x.strip()]:
            walls = []
            texts = []
            errors = 0
            t_batch = time.perf_counter()
            for i in range(n):
                lab, path = fixtures[i % len(fixtures)]
                try:
                    wall, text_out, _ = run_one(lab, path, return_audio=False)
                    walls.append(wall * 1000)
                    texts.append({"label": lab, "text": (text_out or "")[:240]})
                except Exception as e:
                    errors += 1
                    print(f"A→T fail n={n} i={i}: {e}", flush=True)
            batch_s = time.perf_counter() - t_batch
            entry = {
                "simulated_batch": n,
                "note": "sequential single-GPU; not true parallel concurrency",
                "ok": n - errors,
                "failed": errors,
                "wall_p50_ms": round(float(np.median(walls)), 1) if walls else None,
                "wall_p95_ms": round(float(np.percentile(walls, 95)), 1) if walls else None,
                "batch_duration_sec": round(batch_s, 2),
                "effective_qps": round((n - errors) / batch_s, 3) if batch_s > 0 else None,
                "samples": texts[:3],
            }
            results["audio_to_text"].append(entry)
            print(json.dumps(entry, indent=2), flush=True)

    if args.mode in ("gallery", "both"):
        for lab, path in fixtures:
            print(f"gallery {lab} ...", flush=True)
            try:
                wall, text_out, audio_out = run_one(lab, path, return_audio=True)
                out_wav = gallery_dir / f"aa_{lab}_default.wav"
                dur = None
                if audio_out is None:
                    raise RuntimeError("no audio returned")
                arr = audio_out
                if isinstance(arr, (list, tuple)):
                    arr = arr[0]
                if torch.is_tensor(arr):
                    arr = arr.detach().float().cpu().numpy()
                arr = np.asarray(arr, dtype=np.float32).reshape(-1)
                dur = write_wav(out_wav, arr, sr=24000)
                (out_wav.with_suffix(".txt")).write_text(
                    f"label={lab}\ninput={path.name}\nwall_sec={wall:.2f}\n"
                    f"audio_duration_sec={dur}\nrtf={(dur / wall) if wall else None}\n\nTEXT:\n{text_out}\n",
                    encoding="utf-8",
                )
                row = {
                    "label": lab,
                    "file": out_wav.name,
                    "wall_sec": round(wall, 2),
                    "audio_duration_sec": round(dur, 2),
                    "rtf": round(dur / wall, 3) if wall else None,
                    "text": (text_out or "")[:500],
                    "ok": True,
                }
            except Exception as e:
                row = {"label": lab, "ok": False, "error": str(e)}
                print("gallery fail", lab, e, flush=True)
            results["gallery"].append(row)
            print(row, flush=True)

        lines = [
            "# Omni audio→audio listen gallery",
            "",
            "Engine: transformers `Qwen/Qwen2.5-Omni-3B` on 1× RTX 4000 Ada 20GB.",
            "Play the `.wav` files; matching `.txt` has transcript + timing.",
            "",
            "| File | Label | Duration (s) | Wall (s) | RTF |",
            "|------|-------|-------------:|---------:|----:|",
        ]
        for r in results["gallery"]:
            if r.get("ok"):
                lines.append(
                    f"| `{r.get('file','')}` | {r.get('label')} | {r.get('audio_duration_sec')} | "
                    f"{r.get('wall_sec')} | {r.get('rtf')} |"
                )
        (gallery_dir / "LISTEN_ME.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    Path(args.output).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
