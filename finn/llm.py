"""Gemini wrapper: task -> model family chain, response cache, usage log.

- Families (flash-lite / flash / pro) are resolved to real model names by
  listing the models this API key can use, newest stable first.
- Cache key = task + prompt version + input. A cached answer is reused even if
  a different model in the chain produced it: we never pay twice for one input.
- Every call (cache hit or not) is appended to logs/usage.jsonl.
"""
import hashlib
import json
import os
import re
import time

import requests

from . import config, now_ist

API = "https://generativelanguage.googleapis.com/v1beta"
_EXCLUDE = ("image", "tts", "audio", "live", "embedding", "vision", "exp", "robotics", "computer",
            "native", "learnlm", "gemma", "aqa", "veo", "imagen", "banana", "customtools", "thinking")
_models = None
_cache = None
_last_call = {}


class LLMError(RuntimeError):
    pass


class RateLimited(LLMError):
    pass


_cooldown = {}  # model -> time until which we skip it (circuit breaker)
_no_thinking_cfg = set()  # models that reject thinkingConfig


def _key():
    k = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not k:
        raise LLMError("GEMINI_API_KEY not set")
    return k


def _version(name):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def resolve_models():
    """{family: [model names, best first]} for this key."""
    global _models
    if _models is not None:
        return _models
    override = os.environ.get("FINN_MODELS_JSON")
    if override:
        _models = json.loads(override)
        return _models
    names = []
    url = f"{API}/models"
    params = {"key": _key(), "pageSize": 1000}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    for m in r.json().get("models", []):
        n = m["name"].split("/")[-1]
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        if not n.startswith("gemini-") or any(x in n for x in _EXCLUDE):
            continue
        names.append(n)
    fam = {"flash-lite": [], "flash": [], "pro": []}
    for n in names:
        if "flash-lite" in n:
            fam["flash-lite"].append(n)
        elif "flash" in n:
            fam["flash"].append(n)
        elif "-pro" in n:
            fam["pro"].append(n)

    def rank(n):  # newest first, stable before preview, plain alias before dated
        return (-_version(n), "preview" in n, "latest" in n, len(n))

    _models = {k: sorted(v, key=rank)[:2] for k, v in fam.items()}
    return _models


def _cache_path():
    return config.CACHE / "llm.jsonl"


def _load_cache():
    global _cache
    if _cache is None:
        _cache = {}
        p = _cache_path()
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    _cache[row["k"]] = row
                except Exception:
                    continue
    return _cache


def _log(row):
    config.LOGS.mkdir(parents=True, exist_ok=True)
    with open(config.LOGS / "usage.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _call(model, system, prompt, max_out):
    gap = 4.5 if "pro" in model else 2.2  # stay under free-tier RPM
    wait = _last_call.get(model, 0) + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                             "maxOutputTokens": max_out},
    }
    if "pro" not in model and model not in _no_thinking_cfg:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    url = f"{API}/models/{model}:generateContent"
    for attempt in range(3):
        _last_call[model] = time.time()
        r = requests.post(url, params={"key": _key()}, json=body, timeout=180)
        if r.status_code == 400 and "thinkingConfig" in body["generationConfig"]:
            body["generationConfig"].pop("thinkingConfig")  # newer models reject thinkingBudget
            _no_thinking_cfg.add(model)
            continue
        if r.status_code == 429:
            # Don't sit out the retry delay: another model in the chain is usually free.
            raise RateLimited(f"{model} 429")
        if r.status_code == 404:
            _cooldown[model] = time.time() + 10 ** 9
            raise LLMError(f"{model} not available")
        if r.status_code in (500, 503) and attempt < 2:
            print(f"    llm {model}: {r.status_code}, retrying in 3s", flush=True)
            time.sleep(3)
            continue
        if r.status_code != 200:
            raise LLMError(f"{model} {r.status_code}: {r.text[:300]}")
        data = r.json()
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError):
            raise LLMError(f"{model}: empty response {str(data)[:200]}")
        return text, data.get("usageMetadata", {})
    raise LLMError(f"{model}: rate limited")


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            return json.loads(m.group(1))
        raise


def ask(task, system, prompt, *, ticker="", validate=None, max_out=4096):
    """Run `prompt` for `task` and return parsed JSON.

    validate(obj) -> obj or raises ValueError; a failed validation tries the
    next model in the chain once.
    """
    key = hashlib.sha256(f"{task}|{config.PROMPT_VERSION}|{system}|{prompt}".encode()).hexdigest()[:32]
    cache = _load_cache()
    if key in cache:
        row = cache[key]
        _log({"at": now_ist().isoformat(), "ticker": ticker, "task": task, "model": row.get("model"),
              "family": row.get("family"), "in": 0, "out": 0, "cache_hit": True, "list_usd": 0})
        return row["obj"]

    errors = []
    models = resolve_models()
    chain = [m for fam in config.TASK_CHAINS[task] for m in models.get(fam, [])]
    fam_of = {m: fam for fam in config.TASK_CHAINS[task] for m in models.get(fam, [])}
    limited = False
    for rnd in range(2):
        if rnd and not limited:
            break  # second round only helps when the first was rate limits
        live = [m for m in chain if _cooldown.get(m, 0) < time.time()]
        if not live:  # everything cooling down: wait for the soonest, once
            wait = min(_cooldown.get(m, 0) for m in chain) - time.time()
            if rnd or wait > 90:
                break
            print(f"    llm {task}: all models rate-limited, waiting {wait:.0f}s", flush=True)
            time.sleep(max(1, wait))
            live = chain
        for model in live:
            family = fam_of[model]
            try:
                t0 = time.time()
                text, usage = _call(model, system, prompt, max_out)
                print(f"    llm {task} {model} {time.time() - t0:.1f}s in={usage.get('promptTokenCount', 0)} "
                      f"out={usage.get('candidatesTokenCount', 0)}", flush=True)
                obj = parse_json(text)
                if validate:
                    obj = validate(obj)
            except RateLimited as e:
                _cooldown[model] = time.time() + 60
                limited = True
                errors.append(str(e))
                print(f"    llm {model}: rate-limited, skipping it for 60s", flush=True)
                continue
            except (LLMError, ValueError, json.JSONDecodeError, requests.RequestException,
                    AttributeError, TypeError, KeyError, IndexError) as e:  # odd shapes = failed answer
                errors.append(f"{model}: {str(e)[:160]}")
                print(f"    llm {task} {model} failed: {str(e)[:120]}", flush=True)
                continue
            tin = usage.get("promptTokenCount", 0)
            tout = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
            pin, pout = config.LIST_PRICE.get(family, (0, 0))
            _log({"at": now_ist().isoformat(), "ticker": ticker, "task": task, "model": model,
                  "family": family, "in": tin, "out": tout, "cache_hit": False,
                  "list_usd": round(tin / 1e6 * pin + tout / 1e6 * pout, 6)})
            row = {"k": key, "task": task, "model": model, "family": family, "obj": obj}
            cache[key] = row
            config.CACHE.mkdir(parents=True, exist_ok=True)
            with open(_cache_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            return obj
    raise LLMError(f"all models failed for {task}: " + " | ".join(errors[-4:]))
