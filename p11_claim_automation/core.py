# %% [markdown]
# ## Project 11 · Health-insurance claim automation (inspired by "ClaimTrackr")
# **Business problem:** at Nirbhay Health Insurance (fictional), claims officers read every hospital bill, look up the
# member's policy, check the handbook for exclusions, waiting periods and limits, work out the payable amount and
# write a report. It is slow, inconsistent and error-prone, and members wait weeks.
#
# The open-source *ClaimTrackr* project automates this with a paid model that reads the bill, searches the handbook
# and **decides** to accept or reject. This version keeps the idea but changes who decides:
#
# | Step | Who does it here |
# |---|---|
# | Read the bill PDF into structured data | **Model** (then code checks every number is on the bill) |
# | Find the relevant handbook clauses | **Retrieval** over the handbook (free, no paid embeddings) |
# | Exclusions, waiting periods, limits, co-pay, duplicates, payable amount | **Code**: written rules, same answer every time |
# | Second opinion on coverage, with a quoted clause | **Model** (disagreement sends the claim to a person) |
# | Assessment report and member letter | **Model** (code checks they don't contradict the decision) |
# | Pay, reject or investigate | **A claims officer** signs off every outcome |

# %%
import csv
import datetime as dt
import difflib
import io
import json
import os
import re
import sys  # nb:skip

from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))  # nb:skip
from agentkit import (Tool, Toolbox, UNTRUSTED_RULE, ask_json, extract_json,  # nb:skip
                      injection_signals, quote_supported, run_bounded_agent, wrap_untrusted)  # nb:skip

REQUIRED_DOCS = ["claim form", "original bills", "discharge summary", "prescriptions and investigation reports", "photo ID"]
NON_PAYABLE = {"Consumables": "5.3", "Admin": "5.3"}
CATEGORIES = ["Room", "Doctor", "Medicines", "Investigations", "Procedure", "Consumables", "Admin", "Other"]
EXCLUSIONS = {  # handbook clause 4.1 -> keywords that identify it in a diagnosis
    "4.1(a) HIV/AIDS": ["hiv", "aids"], "4.1(b) Alzheimer's disease and dementia": ["alzheimer", "dementia"],
    "4.1(c) Parkinson's disease": ["parkinson"], "4.1(d) Pregnancy and maternity": ["pregnan", "maternity", "childbirth", "caesarean"],
    "4.1(e) Alcohol or substance abuse": ["alcohol", "substance abuse", "de-addiction", "drug abuse"],
    "4.1(f) Self-inflicted injury": ["self-inflicted", "self inflicted", "suicide attempt"],
    "4.1(g) Sexually transmitted disease": ["sexually transmitted", "syphilis", "gonorrh"],
    "4.1(h) Cosmetic treatment": ["cosmetic", "aesthetic"], "4.1(i) Infertility": ["infertility", "ivf"],
    "4.1(j) Experimental treatment": ["experimental", "unproven"],
}
SPECIFIC_WAITING = ["cataract", "hernia", "joint replacement", "kidney stone", "renal calcul", "sinusitis",
                    "piles", "haemorrhoid", "hemorrhoid", "tonsillectomy"]
ACCIDENT_WORDS = ["accident", "fracture", "injury", "trauma"]


def _csv(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_pdf(source):
    """Text of a PDF from a path or an uploaded file object."""
    reader = PdfReader(source if isinstance(source, str) else io.BytesIO(source.read()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def load_data(data_dir="data"):
    handbook_text = read_pdf(os.path.join(data_dir, "member_handbook.pdf"))
    clauses = []
    for m in re.finditer(r"Clause (\d+(?:\.\d+)?)\. ([^\n]+)\n(.*?)(?=\nClause \d|\Z)", handbook_text, re.S):
        clauses.append({"clause": m.group(1), "title": m.group(2).strip(), "text": " ".join(m.group(3).split())})
    return {"policies": {p["policy_no"]: p for p in _csv(os.path.join(data_dir, "policyholders.csv"))},
            "past_claims": _csv(os.path.join(data_dir, "past_claims.csv")),
            "claims": _csv(os.path.join(data_dir, "claims.csv")),
            "handbook_text": handbook_text, "clauses": clauses, "data_dir": data_dir}


# %% [markdown]
# ### Step 1 · Search the handbook (retrieval, free)
# ClaimTrackr used paid OpenAI embeddings and FAISS. Here TF-IDF from scikit-learn does the same job at this scale for
# free and with no downloads. Each result keeps its **clause number**, so every decision can cite its source.

# %%
class HandbookIndex:
    def __init__(self, clauses):
        self.clauses = clauses
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self.matrix = self.vectorizer.fit_transform([f"{c['title']} {c['text']}" for c in clauses])

    def search(self, query, k=3):
        scores = cosine_similarity(self.vectorizer.transform([str(query)]), self.matrix)[0]
        best = scores.argsort()[::-1][:k]
        return [{**self.clauses[i], "score": round(float(scores[i]), 3)} for i in best if scores[i] > 0]


# %% [markdown]
# ### Step 2 · The model reads the bill; code checks the reading
# The model turns the bill text into JSON. Then code checks three things: every number is printed on the bill,
# each line adds up, and the lines add up to the total. A misread bill goes to a person instead of being paid wrongly.

# %%
BILL_SCHEMA = ('{"hospital": str, "bill_no": str, "patient_name": str, "age": number, "admission_date": "YYYY-MM-DD", '
               '"discharge_date": "YYYY-MM-DD", "diagnosis": str, "lines": [{"item": str, "category": one of '
               + json.dumps(CATEGORIES) + ', "qty": number, "rate": number, "amount": number}], "total": number}')


def extract_bill(llm, bill_text):
    result, raw = ask_json(
        llm, "Extract this hospital bill into JSON with exactly this shape: " + BILL_SCHEMA +
        ". Numbers without commas. Copy names, numbers and dates exactly as printed.\n" + wrap_untrusted("BILL", bill_text),
        "You extract data from medical bills. Reply with JSON only. " + UNTRUSTED_RULE, default=None)
    return (result if isinstance(result, dict) else None), raw


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return None


def verify_bill(bill, bill_text):
    problems, digits = [], bill_text.replace(",", "")
    for label in ("bill_no", "patient_name", "admission_date", "discharge_date"):
        if not bill.get(label) or str(bill[label]) not in bill_text:
            problems.append(f"Extracted {label.replace('_', ' ')} ({bill.get(label)}) is not on the bill.")
    lines = bill.get("lines") or []
    for i, l in enumerate(lines, 1):
        q, r, a = _num(l.get("qty")), _num(l.get("rate")), _num(l.get("amount"))
        if a is None or str(int(a)) not in digits:
            problems.append(f"Line {i} amount ({l.get('amount')}) is not on the bill.")
        elif None in (q, r) or abs(q * r - a) > 1:
            problems.append(f"Line {i}: quantity × rate does not equal the amount.")
        if l.get("category") not in CATEGORIES:
            problems.append(f"Line {i}: unknown category '{l.get('category')}'.")
    total = _num(bill.get("total"))
    if total is None or str(int(total)) not in digits:
        problems.append(f"Extracted total ({bill.get('total')}) is not on the bill.")
    elif abs(sum(_num(l.get("amount")) or 0 for l in lines) - total) > 1:
        problems.append("Line amounts do not add up to the bill total.")
    return problems


# %% [markdown]
# ### Step 3 · A second opinion on coverage, with a quote
# The model reads the clauses retrieved for the diagnosis and says whether an exclusion or waiting period applies,
# **quoting the handbook**. Code checks the quote is real. The opinion never decides alone: it is compared with the rules.

# %%
def coverage_opinion(llm, index, diagnosis):
    clauses = index.search(f"{diagnosis} exclusion waiting period", k=4)
    result, _ = ask_json(
        llm, f"Diagnosis: {diagnosis}\nHandbook clauses: {json.dumps(clauses)}\n"
        'Does any exclusion or waiting-period clause apply to this diagnosis? Return JSON: {"applies": true/false, '
        '"clause": "clause number or null", "quote": "exact words copied from the clause, or empty", "reason": "one sentence"}',
        "You are a careful health-insurance claims assessor. Reply with JSON only.", default={})
    result = result if isinstance(result, dict) else {}
    result["quote_verified"] = bool(result.get("quote")) and quote_supported(result["quote"], " ".join(c["text"] for c in clauses))
    result["clauses_seen"] = [c["clause"] for c in clauses]
    return result


# %% [markdown]
# ### Step 4 · The rules decide (plain Python, auditable)
# Each rule returns PASS, FAIL or REVIEW with the clause it comes from. Any FAIL means reject; any REVIEW sends the claim
# to an officer; otherwise the claim is paid in full or in part. A name mismatch or a duplicate bill is never an
# automatic rejection: it is a REVIEW, because a wrong accusation of fraud is costly too.

# %%
def _date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def adjudicate(claim, bill, policy, data, opinion, extraction_problems):
    F = []

    def rule(name, status, clause, detail):
        F.append({"rule": name, "status": status, "clause": clause, "detail": detail})

    admit, discharge = _date(bill.get("admission_date")), _date(bill.get("discharge_date"))
    diagnosis = str(bill.get("diagnosis", "")).lower()
    total = _num(bill.get("total")) or 0
    claimed = _num(claim["claimed_amount_inr"]) or 0
    if extraction_problems:
        rule("Bill reading verified", "REVIEW", "-", "; ".join(extraction_problems))
    if not policy:
        rule("Policy found", "FAIL", "1", f"No policy {claim['policy_no']}.")
        return F
    start = _date(policy["policy_start"])
    days_cover = (admit - start).days if admit and start else -1
    rule("Policy active on admission date", "PASS" if days_cover >= 0 else "FAIL", "2.1",
         f"Policy started {policy['policy_start']}; admitted {bill.get('admission_date')} ({days_cover} days of cover).")
    ratio = difflib.SequenceMatcher(None, policy["member_name"].lower(), str(bill.get("patient_name", "")).lower()).ratio()
    rule("Patient name matches the member", "PASS" if ratio >= 0.92 else "REVIEW", "7.1",
         f"Policy: {policy['member_name']} · bill: {bill.get('patient_name')} (similarity {ratio:.0%}).")
    rule("Amount claimed is within the bill", "PASS" if claimed <= total + 1 else "FAIL", "6.4",
         f"Claimed ₹{claimed:,.0f} vs bill total ₹{total:,.0f}.")
    provided = [d.strip().lower() for d in claim["documents_provided"].split(";")]
    missing = [d for d in REQUIRED_DOCS if d.lower() not in provided]
    rule("Required documents submitted", "PASS" if not missing else "REVIEW", "6.1",
         "All submitted." if not missing else "Missing: " + ", ".join(missing) + ". Ask the member for them.")
    sub = _date(claim["submitted_date"])
    late = (sub - discharge).days if sub and discharge else 0
    rule("Submitted within 30 days of discharge", "PASS" if late <= 30 else "REVIEW", "6.2",
         f"Submitted {late} days after discharge.")
    hits = [k for k, words in EXCLUSIONS.items() if any(w in diagnosis for w in words)]
    llm_says = bool(opinion.get("applies")) and opinion.get("quote_verified")
    if hits and (opinion.get("applies") or not opinion):
        rule("General exclusions", "FAIL", hits[0].split()[0], f"Diagnosis '{bill.get('diagnosis')}' falls under {hits[0]}.")
    elif hits:
        rule("General exclusions", "REVIEW", hits[0].split()[0], f"Rules match {hits[0]} but the model disagrees. A person should decide.")
    elif llm_says and str(opinion.get("clause", "")).startswith("4"):
        rule("General exclusions", "REVIEW", str(opinion.get("clause")),
             f"No rule matched, but the model cites clause {opinion.get('clause')}: \"{opinion.get('quote')}\".")
    else:
        rule("General exclusions", "PASS", "4.1", "No exclusion applies.")
    is_accident = any(w in diagnosis for w in ACCIDENT_WORDS)
    rule("Initial 30-day waiting period", "PASS" if days_cover >= 30 or is_accident else "FAIL", "3.1",
         f"{days_cover} days of cover" + (" (accident: waiting period does not apply)." if is_accident else "."))
    specific = [w for w in SPECIFIC_WAITING if w in diagnosis]
    if specific and days_cover < 730:
        rule("24-month specific-disease waiting period", "FAIL", "3.2",
             f"'{specific[0]}' needs 24 months of cover; the member had {days_cover} days.")
    else:
        rule("24-month specific-disease waiting period", "PASS", "3.2",
             "Not a listed disease." if not specific else f"Listed disease, but {days_cover} days of cover is enough.")
    pre = [p.strip() for p in policy["pre_existing_declared"].split(";") if p.strip()]
    pre_hit = [p for p in pre if p.lower() in diagnosis]
    rule("Pre-existing disease waiting period", "FAIL" if pre_hit and days_cover < 1095 else "PASS", "3.3",
         f"Declared: {', '.join(pre) or 'none'}." + (f" Claim is for '{pre_hit[0]}' within 36 months." if pre_hit and days_cover < 1095 else ""))
    dup = [p for p in data["past_claims"] if p["bill_no"] == bill.get("bill_no")]
    rule("Bill not claimed before", "PASS" if not dup else "REVIEW", "7.1",
         "New bill." if not dup else f"Bill {bill.get('bill_no')} was already paid under {dup[0]['claim_id']} on {dup[0]['paid_date']}.")
    remaining = float(policy["sum_insured_inr"]) - float(policy["claimed_so_far_inr"])
    rule("Sum insured available", "PASS" if remaining > 0 else "FAIL", "2.1", f"₹{remaining:,.0f} remaining this year.")
    return F


def settlement(bill, policy, claimed):
    """Line-by-line payable amount with the clause behind every deduction."""
    si = float(policy["sum_insured_inr"])
    cap = 0.01 * si
    rows, deductions = [], []
    for l in bill.get("lines") or []:
        amount, qty, rate = _num(l.get("amount")) or 0, _num(l.get("qty")) or 1, _num(l.get("rate")) or 0
        payable = amount
        if l.get("category") in NON_PAYABLE:
            payable = 0
            deductions.append({"item": l["item"], "amount": amount, "clause": NON_PAYABLE[l["category"]], "why": "non-payable item"})
        elif l.get("category") == "Room" and rate > cap:
            payable = cap * qty
            deductions.append({"item": l["item"], "amount": amount - payable, "clause": "5.1",
                               "why": f"room rent above ₹{cap:,.0f}/day limit"})
        rows.append({"item": l.get("item"), "category": l.get("category"), "billed": amount, "payable": payable})
    admissible = sum(r["payable"] for r in rows)
    copay = round(0.10 * admissible) if int(policy["age"]) >= 60 else 0
    if copay:
        deductions.append({"item": "Co-payment (member aged 60+)", "amount": copay, "clause": "5.2", "why": "10% co-payment"})
    remaining = si - float(policy["claimed_so_far_inr"])
    final = max(0, min(admissible - copay, claimed, remaining))
    return {"rows": rows, "deductions": deductions, "admissible": admissible, "copay": copay,
            "claimed": claimed, "remaining_sum_insured": remaining, "payable": round(final)}


def verdict_from(findings, settle):
    if any(f["status"] == "FAIL" for f in findings):
        return "REJECT"
    if any(f["status"] == "REVIEW" for f in findings):
        return "NEEDS_REVIEW"
    return "APPROVE" if settle and settle["payable"] >= settle["claimed"] else "PARTIAL_APPROVAL"


# %% [markdown]
# ### Step 5 · The model writes; code checks the writing
# The report and the member letter are written by the model from the decision, the findings and the clauses.
# Code then checks that the text doesn't contradict the decision and only uses rupee amounts that were calculated.

# %%
def check_text(text, verdict, allowed_amounts):
    flags = []
    t = text.lower()
    if verdict == "REJECT" and re.search(r"\b(claim (is|has been) (approved|accepted)|we (are pleased|will pay))", t):
        flags.append("Text suggests approval, but the decision is REJECT.")
    if verdict in ("APPROVE", "PARTIAL_APPROVAL") and re.search(r"\bclaim (is|has been) (rejected|denied|declined)", t):
        flags.append("Text suggests rejection, but the decision is to pay.")
    allowed = {int(round(a)) for a in allowed_amounts}
    for amt in re.findall(r"(?:₹|rs\.?|inr)\s?([\d,]+(?:\.\d+)?)", text, flags=re.I):
        value = int(round(float(amt.replace(",", "") or 0)))
        if value and value not in allowed:
            flags.append(f"Text mentions ₹{value:,}, which is not one of the calculated amounts.")
    return flags


def write_report(llm, claim, bill, findings, settle, verdict, clauses):
    return llm.ask(
        "Write a claim assessment report for a claims officer with these sections: Executive Summary, Claim Details, "
        "Document Verification, Rule Assessment, Settlement Calculation, Fraud Indicators, Recommendation.\n"
        f"DECISION (do not change it): {verdict}\nClaim form: {json.dumps(claim)}\nBill (extracted): {json.dumps(bill)[:3000]}\n"
        f"Rule findings: {json.dumps(findings)}\nSettlement (use these numbers only): {json.dumps(settle)}\n"
        f"Relevant handbook clauses: {json.dumps(clauses)[:3000]}\n"
        "Cite clause numbers for every finding. Do not invent facts, amounts or clauses. Use ₹ for amounts.",
        "You write clear, factual insurance claim reports.").strip()


def payable_for(verdict, settle):
    return settle["payable"] if settle and verdict in ("APPROVE", "PARTIAL_APPROVAL") else 0


def write_letter(llm, claim, verdict, findings, settle):
    reasons = [f for f in findings if f["status"] != "PASS"]
    amount = (f"Amount payable: ₹{payable_for(verdict, settle):,}. " if verdict in ("APPROVE", "PARTIAL_APPROVAL")
              else "No amount is payable at this stage; do not mention any amount except the amount claimed. ")
    return llm.ask(
        f"Write a short, polite letter to {claim['claimant_name']} about claim {claim['claim_id']}. Decision: {verdict}. "
        f"{amount}Reasons with clauses: {json.dumps(reasons)}. "
        f"Deductions: {json.dumps(settle['deductions'] if settle else [])}. "
        "Explain each reason in plain words with its clause number. For a rejection or partial payment, say the member "
        "can ask for a review under clause 6.3. For NEEDS_REVIEW, say what we need or are checking. Sign as "
        "'Claims Team, Nirbhay Health Insurance'. Use ₹ for amounts and do not mention any other amounts.",
        "You write empathetic, accurate insurance letters.").strip()


# %% [markdown]
# ### Step 6 · Claims that need a person get an investigator's brief
# For NEEDS_REVIEW claims, a bounded agent uses read-only tools (handbook, policy, past claims) to prepare notes for
# the officer: what is odd, what to check, and what to ask the member or hospital.

# %%
def make_toolbox(data, index):
    return Toolbox([
        Tool("search_handbook", lambda q: index.search(q, k=3), "Find handbook clauses on a topic.", "a few keywords"),
        Tool("policy_record", lambda p: data["policies"].get(str(p).strip(), {"error": "No such policy"}),
             "A member's policy record.", "a policy number such as NHP-1005"),
        Tool("claim_history", lambda p: [c for c in data["past_claims"] if str(p).strip() in (c["policy_no"], c["bill_no"])]
             or {"result": "No past claims."}, "Past claims for a policy number or a bill number.", "a policy or bill number"),
    ])


def investigate(llm, data, index, claim, bill, findings, max_steps=4):
    open_items = [f for f in findings if f["status"] != "PASS"]
    return run_bounded_agent(
        llm, goal=("Prepare an investigation brief for a claims officer: what needs checking, why (with clause numbers), "
                   "and the exact questions to ask the member or hospital. Finish with 3-6 bullet points."),
        toolbox=make_toolbox(data, index),
        context=f"Claim: {json.dumps(claim)}\nBill: {json.dumps(bill)[:2000]}\nOpen findings: {json.dumps(open_items)}",
        max_steps=max_steps, role="You are a fair, careful claims investigator.")


# %% [markdown]
# ### Step 7 · The whole pipeline ends in a proposal for a claims officer
# Nothing is paid, rejected or sent automatically. Payouts, rejections and investigations each wait for a named officer.

# %%
def process_claim(llm, data, index, claim, queue, bill_text=None):
    if bill_text is None:
        bill_text = read_pdf(os.path.join(data["data_dir"], claim["bill_file"]))
    signals = injection_signals(bill_text + " " + claim.get("claim_reason", ""))
    bill, raw = extract_bill(llm, bill_text)
    if not bill:
        item = queue.propose("manual_review", f"{claim['claim_id']}: bill could not be read", {"claim_id": claim["claim_id"]},
                             flags=["Bill extraction failed; key in manually."])
        return {"claim": claim, "bill": None, "verdict": "NEEDS_REVIEW", "findings": [], "proposal": item}
    problems = verify_bill(bill, bill_text)
    index_hits = index.search(f"{bill.get('diagnosis', '')} {claim.get('claim_reason', '')}", k=4)
    opinion = coverage_opinion(llm, index, bill.get("diagnosis", ""))
    policy = data["policies"].get(claim["policy_no"])
    findings = adjudicate(claim, bill, policy, data, opinion, problems)
    if signals:
        findings.append({"rule": "No instructions hidden in documents", "status": "REVIEW", "clause": "7.1",
                         "detail": f"Instruction-like text found: {signals}"})
    settle = settlement(bill, policy, _num(claim["claimed_amount_inr"]) or 0) if policy else None
    verdict = verdict_from(findings, settle)
    cited = sorted({f["clause"].split("(")[0] for f in findings if f["status"] != "PASS"} | {c["clause"] for c in index_hits})
    clauses = [c for c in data["clauses"] if c["clause"] in cited]
    report = write_report(llm, claim, bill, findings, settle, verdict, clauses)
    letter = write_letter(llm, claim, verdict, findings, settle)
    amounts = [_num(claim["claimed_amount_inr"]) or 0, _num(bill.get("total")) or 0]
    if settle:
        amounts += [settle["payable"], settle["admissible"], settle["copay"], settle["remaining_sum_insured"],
                    0.01 * float(policy["sum_insured_inr"])] + [d["amount"] for d in settle["deductions"]] + \
                   [r["billed"] for r in settle["rows"]] + [r["payable"] for r in settle["rows"]] + \
                   [_num(l.get("rate")) or 0 for l in bill.get("lines") or []]
    text_flags = check_text(report, verdict, amounts) + check_text(letter, verdict, amounts)
    agent = investigate(llm, data, index, claim, bill, findings) if verdict == "NEEDS_REVIEW" else None
    kind = {"APPROVE": "settlement", "PARTIAL_APPROVAL": "settlement", "REJECT": "rejection",
            "NEEDS_REVIEW": "investigation"}[verdict]
    open_findings = [f"{f['status']} · {f['rule']} (clause {f['clause']}): {f['detail']}" for f in findings if f["status"] != "PASS"]
    item = queue.propose(
        kind, f"{claim['claim_id']} · {claim['claimant_name']} · {verdict.replace('_', ' ')} · payable ₹{payable_for(verdict, settle):,}",
        {"claim_id": claim["claim_id"], "verdict": verdict, "payable_inr": payable_for(verdict, settle),
         "provisional_payable_inr": settle["payable"] if settle and verdict == "NEEDS_REVIEW" else None,
         "member_letter": letter, "investigation_brief": str(agent["answer"]) if agent else ""},
        evidence=[{"clause": c["clause"], "text": c["text"]} for c in clauses], flags=open_findings + text_flags)
    return {"claim": claim, "bill": bill, "extraction_problems": problems, "opinion": opinion, "findings": findings,
            "settlement": settle, "verdict": verdict, "report": report, "letter": letter, "text_flags": text_flags,
            "agent": agent, "proposal": item}


def record_decision(data_dir="data"):
    """Executor: writes the officer-approved outcome to decisions.csv. It does not move money."""
    def run(payload):
        path = os.path.join(data_dir, "decisions.csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["claim_id", "verdict", "payable_inr"])
            w.writerow([payload["claim_id"], payload["verdict"], payload["payable_inr"]])
        return "recorded in decisions.csv; letter ready to send"
    return run


# %% [markdown]
# ### Step 8 · A member help-desk chatbot over the handbook
# ClaimTrackr's second goal was to explain the membership handbook. This agent answers from the handbook only and must
# cite clause numbers; code checks every clause it cites exists.

# %%
def ask_handbook(llm, data, index, question):
    toolbox = Toolbox([Tool("search_handbook", lambda q: index.search(q, k=3), "Find handbook clauses on a topic.", "a few keywords")])
    res = run_bounded_agent(llm, goal=("Answer this member question using only the handbook, in plain words, and cite clause "
                                       f"numbers like (clause 3.2). If the handbook does not say, say so. Question: {question}"),
                            toolbox=toolbox, max_steps=3, role="You are a helpful insurance help-desk assistant.")
    known = {c["clause"] for c in data["clauses"]}
    cited = set(re.findall(r"clause (\d+(?:\.\d+)?)", str(res["answer"]), flags=re.I))
    res["unknown_clauses"] = sorted(cited - known)
    return res
