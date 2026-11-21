import os, sys  # nb:skip
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))  # nb:skip
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # nb:skip
from agentkit import *  # nb:skip
from core import *  # nb:skip
GROQ_API_KEY = os.environ["GROQ_API_KEY"]  # nb:skip
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # nb:skip

# %% [markdown]
# ## Run it
# Seven claims arrive, each with a hospital bill PDF. Read the handbook clauses and one bill before running anything.

# %%
llm = LLM(GROQ_API_KEY)
data = load_data("data")
index = HandbookIndex(data["clauses"])
queue = ApprovalQueue(log_path="data/audit_log.jsonl")
for c in data["clauses"]:
    print(f"Clause {c['clause']:<4} {c['title']}")
print()
for c in data["claims"]:
    print(c["claim_id"], "|", c["claimant_name"], "|", c["claim_reason"], "| claimed ₹", c["claimed_amount_inr"])
print("\n" + read_pdf("data/bills/CLM-1107.pdf"))

# %% [markdown]
# ### Retrieval: which clauses matter for a diagnosis?

# %%
for query in ["cataract surgery", "Alzheimer's disease", "room rent private room", "gloves and masks"]:
    print(query, "→", [(r["clause"], r["title"], r["score"]) for r in index.search(query)])

# %% [markdown]
# ### Process one clean claim end to end (CLM-1101, dengue fever)
# Follow the chain: extraction → verification → rules → settlement → report.

# %%
res = process_claim(llm, data, index, data["claims"][0], queue)
print("Extracted bill:", json.dumps(res["bill"], indent=1)[:800])
print("\nExtraction problems:", res["extraction_problems"] or "none")
for f in res["findings"]:
    print(f"  {f['status']:<6} {f['rule']:<42} clause {f['clause']:<8} {f['detail']}")
print("\nDECISION:", res["verdict"], "· payable ₹", res["settlement"]["payable"])

# %% [markdown]
# ### The report and the member letter (written by the model, checked by code)

# %%
print(res["report"])
print("\n--- Letter to member ---\n", res["letter"])
print("\nText checks:", res["text_flags"] or "passed")

# %% [markdown]
# ### Process the other six claims
# Predict each outcome first. Hints: one claims more than the bill, one is an excluded disease, one is inside a waiting
# period, one has a name mismatch and a missing document, one reuses an old bill, and one gets deductions and a co-payment.

# %%
results = {"CLM-1101": res}
for claim in data["claims"][1:]:
    r = process_claim(llm, data, index, claim, queue)
    results[claim["claim_id"]] = r
    print(f"\n{claim['claim_id']} {claim['claimant_name']}: {r['verdict']}")
    for f in r["findings"]:
        if f["status"] != "PASS":
            print(f"   {f['status']} · {f['rule']} (clause {f['clause']}): {f['detail']}")
    if r["settlement"] and r["settlement"]["deductions"]:
        for d in r["settlement"]["deductions"]:
            print(f"   deduction ₹{d['amount']:,.0f} · {d['item']} (clause {d['clause']}, {d['why']})")

# %% [markdown]
# ### The investigator's brief for a claim that needs a person (CLM-1105)

# %%
print(results["CLM-1105"]["agent"]["answer"])

# %% [markdown]
# ### A claims officer signs off every outcome
# Approvals and rejections are recorded only after a named officer agrees. Investigations stay open.

# %%
for item in queue.pending():
    if item["kind"] in ("settlement", "rejection"):
        queue.approve(item["id"], approver="Claims officer A. Kulkarni", executor=record_decision("data"))
print(open("data/decisions.csv").read())
print("Still open:", [i["summary"] for i in queue.pending()])

# %% [markdown]
# ### The member help-desk chatbot

# %%
for q in ["Is cataract surgery covered in my first year?", "Will you pay for gloves and masks used in hospital?"]:
    ans = ask_handbook(llm, data, index, q)
    print("Q:", q, "\nA:", ans["answer"], "\n   clauses that don't exist:", ans["unknown_clauses"] or "none", "\n")

# %% [markdown]
# ### Try this
# 1. In ClaimTrackr the model decides. Here it can't. Find one claim where letting the model decide could have gone wrong.
# 2. Change Gopal Menon's age to 59 in `policyholders.csv`. What changes in his settlement, and which clause explains it?
# 3. Add "kidney stone" treatment for Meera Kapoor. Which rule catches it, and what would change after 24 months?
# 4. Upload your own bill PDF in the app (make one with a word processor). Does extraction verification catch a misread?
# 5. **Discussion:** CLM-1106 reuses a bill that was already paid. Should that be an automatic rejection? Who is harmed if
#    the system is wrong either way?
