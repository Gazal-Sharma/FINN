"""Golden set: real-style NSE filing subjects -> expected category and tier.

Run: python -m pytest tests/ -q   (or: python tests/test_rules.py)
The rules decide what the investor sees first, so they're the part worth guarding.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finn import classify, research  # noqa: E402

DIR = "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent"
CALL = "Analysts/Institutional Investor Meet/Con. Call Updates"
CASES = [
    ("Outcome of Board Meeting", "approved the Unaudited Financial Results for the quarter ended September 30, 2026", "results", "act"),
    ("Financial Result Updates", "Financial results for the period ended September 30, 2026", "results", "act"),
    ("Board Meeting Intimation", "to consider and approve the financial results for the quarter", "results", "know"),
    ("Investor Presentation", "Investor presentation on Q2 FY27 results", "results", "know"),
    ("Copy of Newspaper Publication", "Newspaper publication of financial results", "unclassified", "hidden"),
    (DIR, "Resignation of Mr. A as Chief Financial Officer with immediate effect", "management_change", "act"),
    (DIR, "Appointment of Mr. B as Managing Director and CEO", "management_change", "act"),
    (DIR, "Appointment of Ms. C as Independent Director", "management_change", "know"),
    (DIR, "Change in Company Secretary and Compliance Officer", "management_change", "know"),
    (DIR, "Re-appointment of Statutory Auditors", "unclassified", "hidden"),
    ("Acquisition", "acquisition of 100% stake in XYZ GmbH", "M&A", "act"),
    ("Scheme of Arrangement", "scheme of amalgamation of wholly owned subsidiary", "M&A", "act"),
    ("Allotment of Securities", "allotment of shares under ESOP scheme 2019", "unclassified", "hidden"),
    ("Qualified Institutional Placement", "opening of QIP issue", "fund_raise", "act"),
    ("Credit Rating", "CRISIL has reaffirmed the rating AAA/Stable", "credit_rating", "hidden"),
    ("Credit Rating", "ICRA has downgraded the long-term rating", "credit_rating", "act"),
    ("Trading Window-XBRL", "closure of trading window", "unclassified", "hidden"),
    (CALL, "Transcript of the earnings conference call held on October 16, 2026", "earnings_call", "know"),
    (CALL, "Audio recording of the earnings call", "earnings_call", "hidden"),
    (CALL, "Schedule of analyst / institutional investor meetings", "investor_meetings", "hidden"),
    ("Bagging/Receiving of orders/contracts", "received an order worth Rs 450 crore from PGCIL", "press_release", "know"),
    ("Clarification - Spurt in Volume", "clarification on increase in volume", "press_release", "know"),
    ("Certificate under SEBI (Depositories and Participants) Regulations, 2018", "certificate under reg 74(5)", "unclassified", "hidden"),
    ("Disclosure under SEBI Takeover Regulations", "Regulation 29 disclosure by promoter", "insider_trading", "know"),
    ("Dividend", "Record date for interim dividend", "dividend", "know"),
    ("Shareholders meeting", "Notice of 45th AGM", "agm_egm", "hidden"),
    ("Postal Ballot", "Postal ballot notice", "postal_ballot", "hidden"),
    ("Updates", "Update on pledge of promoter shares", "pledging", "act"),
    ("Litigation / Dispute / Regulatory Action", "receipt of show cause notice from GST authority", "litigation", "know"),
    ("Press Release", "launch of new product range", "press_release", "know"),
]


def test_rules():
    bad = []
    for subj, text, cat, tier in CASES:
        v = classify.rule_verdict({"subject": subj, "text": text})
        got = (v or {}).get("category"), (v or {}).get("tier")
        if got != (cat, tier):
            bad.append(f"{subj[:30]!r} / {text[:40]!r}: expected {(cat, tier)}, got {got}")
    assert not bad, "\n".join(bad)


def test_session_mapping():
    s = ["2026-11-12", "2026-11-13"]
    assert classify.reaction_session("2026-11-13T10:00:00+05:30", s) == "2026-11-13"   # in market hours
    assert classify.reaction_session("2026-11-13T18:00:00+05:30", s) == "2026-11-16"   # after close Fri -> Mon


def test_horizons():
    assert research.parse_horizon("FY27") == ("fy", 2027)
    assert research.parse_horizon("Q3 FY27") == ("q", "Dec 2026")
    assert research.parse_horizon("H1FY28") == ("h", (2028, 1))
    assert research.parse_horizon("medium term") is None


if __name__ == "__main__":
    for fn in (test_rules, test_session_mapping, test_horizons):
        fn()
    print("all passed")
