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
import threading
import time

import requests

from . import config, now_ist

API = "https://generativelanguage.googleapis.com/v1beta"
GROQ_API = "https://api.groq.com/openai/v1"
_EXCLUDE = ("image", "tts", "audio", "live", "embedding", "vision", "exp", "robotics", "computer",
            "native", "learnlm", "gemma", "aqa", "veo", "imagen", "banana", "customtools", "thinking")
_models = None
_cache = None
_last_call = {}


class LLMError(RuntimeError):
    pass


class RateLimited(LLMError):
    def __init__(self, msg, wait=30.0, daily=False):
        super().__init__(msg)
        self.wait, self.daily = wait, daily


class QuotaExhausted(LLMError):
    pass


_cooldown = {}  # model -> time until which we skip it (circuit breaker)
_no_thinking_cfg = set()  # models that reject thinkingConfig
_exhausted = set()        # models whose free daily quota is used up
_lock = threading.Lock()  # cache file + shared dicts (research reads transcripts in parallel)
_model_locks = {}         # one request at a time per model, paced below the free-tier RPM
# Wait the pipeline accepts before giving up on rate limits; the API answers a person, so it's short.
MAX_WAIT = float(os.environ.get("FINN_LLM_MAX_WAIT", "20" if config.RUNTIME == "api" else "900"))


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

    _models = {k: sorted(v, key=rank)[:3] for k, v in fam.items()}  # each model has its own free quota
    _models["groq"] = _groq_models()
    return _models


def _groq_models():
    """Groq chat models this key can use, best first; [] when there's no key."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(f"{GROQ_API}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
        r.raise_for_status()
        avail = {m["id"]: m for m in r.json().get("data", []) if m.get("active", True)}
    except Exception as e:
        print("groq model list failed:", str(e)[:120], flush=True)
        return []
    skip = ("whisper", "tts", "guard", "compound", "playai", "orpheus", "prompt")
    pref = [m for m in config.GROQ_PREFERRED if m in avail]
    rest = sorted((m for m, d in avail.items() if m not in pref and not any(x in m for x in skip)
                   and (d.get("context_window") or 0) >= 32000), key=lambda m: -(avail[m].get("context_window") or 0))
    return ["groq:" + m for m in (pref + rest)[:3]]


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
    with _lock, open(config.LOGS / "usage.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _call(model, system, prompt, max_out):
    if model.startswith("groq:"):
        return _call_groq(model, system, prompt, max_out)
    gap = 12.0 if "pro" in model else 4.5  # ~5 / ~13 requests a minute: under free-tier limits
    with _lock:
        lk = _model_locks.setdefault(model, threading.Lock())
    with lk:  # requests to one model go one after another, spaced by `gap`
        wait = _last_call.get(model, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[model] = time.time()
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
        r = requests.post(url, params={"key": _key()}, json=body, timeout=180)
        if r.status_code == 400 and "thinkingConfig" in body["generationConfig"]:
            body["generationConfig"].pop("thinkingConfig")  # newer models reject thinkingBudget
            _no_thinking_cfg.add(model)
            continue
        if r.status_code == 429:
            m = re.search(r'"retryDelay":\s*"([\d.]+)s?"', r.text)
            daily = "PerDay" in r.text or "per day" in r.text.lower()
            raise RateLimited(f"{model} 429", wait=float(m.group(1)) if m else 30.0, daily=daily)
        if r.status_code == 404:
            _cooldown[model] = time.time() + 10 ** 9
            raise LLMError(f"{model} not available")
        if r.status_code in (500, 503) and attempt < 2:
            print(f"    llm {model}: {r.status_code}, retrying in {5 * (attempt + 1)}s", flush=True)
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise LLMError(f"{model} {r.status_code}: {r.text[:300]}")
        data = r.json()
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError):
            raise LLMError(f"{model}: empty response {str(data)[:200]}")
        return text, data.get("usageMetadata", {})
    raise LLMError(f"{model}: server errors")


class TooLarge(LLMError):
    pass


def _call_groq(model, system, prompt, max_out):
    """OpenAI-compatible chat call; same JSON-only contract as Gemini."""
    name = model.split(":", 1)[1]
    with _lock:
        lk = _model_locks.setdefault(model, threading.Lock())
    with lk:
        wait = _last_call.get(model, 0) + 2.5 - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[model] = time.time()
    body = {"model": name, "temperature": 0, "max_tokens": max_out,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system + "\nReply with JSON only."},
                         {"role": "user", "content": prompt}]}
    if "gpt-oss" in name:
        body["reasoning_effort"] = "low"
    r = requests.post(f"{GROQ_API}/chat/completions", json=body, timeout=120,
                      headers={"Authorization": f"Bearer {os.environ.get('GROQ_API_KEY', '')}"})
    if r.status_code == 413 or "reduce the length" in r.text or "Request too large" in r.text:
        raise TooLarge(f"{model}: request too large for its free tier")
    if r.status_code == 429:
        ra = r.headers.get("retry-after")
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", r.text)
        wait = float(ra) if ra else (float(m.group(1) or 0) * 60 + float(m.group(2)) if m else 30.0)
        daily = any(x in r.text for x in ("per day", "(TPD)", "(RPD)"))
        raise RateLimited(f"{model} 429", wait=wait, daily=daily and wait > 120)
    if r.status_code == 400 and "json" in r.text.lower() and "response_format" in body:
        body.pop("response_format")  # a few models don't support JSON mode; parse_json copes
        r = requests.post(f"{GROQ_API}/chat/completions", json=body, timeout=120,
                          headers={"Authorization": f"Bearer {os.environ.get('GROQ_API_KEY', '')}"})
    if r.status_code == 404:
        _cooldown[model] = time.time() + 10 ** 9
        raise LLMError(f"{model} not available")
    if r.status_code != 200:
        raise LLMError(f"{model} {r.status_code}: {r.text[:300]}")
    d = r.json()
    text = d["choices"][0]["message"].get("content") or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    u = d.get("usage", {})
    return text, {"promptTokenCount": u.get("prompt_tokens", 0), "candidatesTokenCount": u.get("completion_tokens", 0)}


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
    fams = config.TASK_CHAINS[task]
    only = [f.strip() for f in os.environ.get("FINN_ONLY_FAMILIES", "").split(",") if f.strip()]
    if only:  # e.g. FINN_ONLY_FAMILIES=groq to test the fallback on its own
        fams = [f for f in fams if f in only] or fams
    chain = [m for fam in fams for m in models.get(fam, [])]
    fam_of = {m: fam for fam in fams for m in models.get(fam, [])}
    tried_ok = set()          # models that answered but failed validation: don't ask them again
    waited = 0.0
    while True:
        live = [m for m in chain if m not in _exhausted and m not in tried_ok and _cooldown.get(m, 0) <= time.time()]
        if not live:
            pending = [m for m in chain if m not in _exhausted and m not in tried_ok]
            if not pending:
                if all(m in _exhausted for m in chain):
                    raise QuotaExhausted(f"free daily quota used up for {task} ({', '.join(chain)})")
                break
            # Rate-limited, not out of quota: slow down and try again rather than fail.
            wait = max(1.0, min(_cooldown.get(m, 0) for m in pending) - time.time())
            if waited + wait > MAX_WAIT:
                break
            print(f"    llm {task}: rate limit, slowing down {wait:.0f}s", flush=True)
            time.sleep(wait)
            waited += wait
            continue
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
            except TooLarge as e:
                tried_ok.add(model)
                errors.append(str(e))
                print(f"    llm {model}: prompt too large for it, skipping", flush=True)
                continue
            except RateLimited as e:
                if e.daily and e.wait > 120:
                    _exhausted.add(model)
                    print(f"    llm {model}: free daily quota used up", flush=True)
                else:
                    _cooldown[model] = time.time() + min(max(e.wait, 5.0), 120.0) + 1
                    print(f"    llm {model}: rate-limited, pausing it {e.wait:.0f}s", flush=True)
                errors.append(str(e))
                continue
            except (LLMError, ValueError, json.JSONDecodeError, requests.RequestException,
                    AttributeError, TypeError, KeyError, IndexError) as e:  # odd shapes = failed answer
                tried_ok.add(model)
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
            with _lock:
                cache[key] = row
                config.CACHE.mkdir(parents=True, exist_ok=True)
                with open(_cache_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            return obj
    raise LLMError(f"all models failed for {task}: " + " | ".join(errors[-4:]))
