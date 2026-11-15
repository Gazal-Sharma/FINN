"""Static configuration: companies, paths, tier weights, model routing."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# On Vercel the repo is read-only; everything writable goes to /tmp.
RUNTIME = os.environ.get("FINN_RUNTIME", "pipeline")  # "pipeline" | "api"
WRITE_ROOT = Path("/tmp/finn") if RUNTIME == "api" else ROOT

RAW = WRITE_ROOT / "raw"
CACHE = WRITE_ROOT / "cache"
LOGS = WRITE_ROOT / "logs"
PUBLIC_DATA = ROOT / "public" / "data"

RULES_VERSION = "2026-11-15.1"
PROMPT_VERSION = "2026-11-15.1"

# ticker -> (display name, spoken name, sector, is_lender, BSE code or None)
# BSE codes are only used if the NSE fetch fails. CDSL is listed on NSE only.
PORTFOLIO = {
    "INFY":       ("Infosys", "Infosys", "IT services", False, "500209"),
    "HCLTECH":    ("HCL Technologies", "H C L Tech", "IT services", False, "532281"),
    "PERSISTENT": ("Persistent Systems", "Persistent", "IT services", False, "533179"),
    "HDFCBANK":   ("HDFC Bank", "H D F C Bank", "Bank", True, "500180"),
    "ICICIBANK":  ("ICICI Bank", "I C I C I Bank", "Bank", True, "532174"),
    "BAJFINANCE": ("Bajaj Finance", "Bajaj Finance", "NBFC", True, "500034"),
    "CDSL":       ("CDSL", "C D S L", "Market infra", False, None),
    "TITAN":      ("Titan Company", "Titan", "Consumer", False, "500114"),
    "TRENT":      ("Trent", "Trent", "Retail", False, "500251"),
    "ETERNAL":    ("Eternal", "Eternal", "Internet", False, "543320"),
    "LT":         ("Larsen & Toubro", "L and T", "Engineering", False, "500510"),
    "POLYCAB":    ("Polycab India", "Polycab", "Cables & wires", False, "542652"),
    "DIXON":      ("Dixon Technologies", "Dixon", "Electronics mfg", False, "540699"),
    "RELIANCE":   ("Reliance Industries", "Reliance", "Conglomerate", False, "500325"),
    "BHARTIARTL": ("Bharti Airtel", "Airtel", "Telecom", False, "532454"),
    "SUNPHARMA":  ("Sun Pharma", "Sun Pharma", "Pharma", False, "524715"),
    "MARUTI":     ("Maruti Suzuki", "Maruti", "Autos", False, "532500"),
    "INDIGO":     ("InterGlobe Aviation", "IndiGo", "Airlines", False, "539448"),
}

RESEARCH_SET = {
    "INFY":      ("Infosys", "Infosys", "IT services", False, "500209"),
    "KPITTECH":  ("KPIT Technologies", "K P I T", "Auto software", False, "542651"),
    "POLYCAB":   ("Polycab India", "Polycab", "Cables & wires", False, "542652"),
    "TATAPOWER": ("Tata Power", "Tata Power", "Power", False, "500400"),
    "DMART":     ("Avenue Supermarts", "D Mart", "Retail", False, "540376"),
}

LENDER_HINTS = ("BANK", "FIN", "HDFC", "LIC", "CHOLA", "SHRIRAM", "MUTHOOT", "PFC", "RECLTD", "IRFC")

INDEX_YF = "^NSEI"

TIER_BASE = {"act": 100, "know": 50, "hidden": 0}

# Gemini only. Families are resolved to concrete model names at runtime by
# listing models, so the code survives Google renaming/retiring versions.
TASK_CHAINS = {
    "classify":  ["flash-lite", "flash"],
    "summarize": ["flash-lite", "flash"],
    "extract":   ["flash", "flash-lite"],
    "synthesis": ["pro", "flash"],
}

# Approximate paid list prices (USD per 1M tokens, input/output) used only to
# report what the run *would* have cost; we run on the free tier.
LIST_PRICE = {
    "flash-lite": (0.10, 0.40),
    "flash": (0.30, 2.50),
    "pro": (1.25, 10.00),
}


def company(ticker):
    t = ticker.upper()
    row = PORTFOLIO.get(t) or RESEARCH_SET.get(t)
    if row:
        name, spoken, sector, lender, bse = row
    else:
        name, spoken, sector, bse = t, t, "", None
        lender = any(h in t for h in LENDER_HINTS)
    return {"t": t, "name": name, "spoken": spoken, "sector": sector, "lender": lender, "bse": bse}
