"""Health-insurance Claim Automation — run with:  streamlit run p11_claim_automation/app.py"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "common")]

import pandas as pd
import streamlit as st

import core
from ui import get_queue, render_audit, render_queue, show_flags, show_trace, sidebar_llm

st.set_page_config(page_title="Claim Automation", layout="wide")
st.title("🏥 Claim Automation · Nirbhay Health (fictional)")
st.caption("The model reads bills and writes reports. Written rules decide, citing handbook clauses. "
           "A claims officer signs off every payout, rejection and investigation.")

llm, approver = sidebar_llm()
DATA_DIR = os.path.join(HERE, "data")
data = core.load_data(DATA_DIR)
queue = get_queue(os.path.join(DATA_DIR, "audit_log.jsonl"))
results = st.session_state.setdefault("results", {})


@st.cache_resource
def get_index():
    return core.HandbookIndex(data["clauses"])


index = get_index()
tab_claim, tab_result, tab_chat, tab_queue, tab_audit, tab_data = st.tabs(
    ["Submit a claim", "Assessment", "Handbook chatbot", "Approval queue", "Audit log", "Policies & handbook"])

with tab_claim:
    mode = st.radio("Claim", ["Use a sample claim", "Enter a new claim"], horizontal=True)
    if mode == "Use a sample claim":
        labels = {f"{c['claim_id']} · {c['claimant_name']} · {c['claim_reason']}": c for c in data["claims"]}
        claim = labels[st.selectbox("Sample claim", list(labels))]
        st.json(claim, expanded=False)
        bill_text = core.read_pdf(os.path.join(DATA_DIR, claim["bill_file"]))
    else:
        with st.form("claim_form"):
            c1, c2 = st.columns(2)
            policy_no = c1.selectbox("Policy number", list(data["policies"]))
            name = c2.text_input("Claimant name", data["policies"][policy_no]["member_name"])
            reason = c1.text_input("Claim reason")
            facility = c2.text_input("Medical facility")
            admit = c1.date_input("Admission date", dt.date(2026, 10, 1))
            discharge = c2.date_input("Discharge date", dt.date(2026, 10, 3))
            claimed = c1.number_input("Total claim amount (₹)", 0, 2000000, 20000, 500)
            submitted = c2.date_input("Submitted on", dt.date(2026, 11, 15))
            docs = st.multiselect("Documents provided", core.REQUIRED_DOCS, core.REQUIRED_DOCS)
            upload = st.file_uploader("Medical bill (PDF with text)", type="pdf")
            ok = st.form_submit_button("Use this claim")
        claim, bill_text = st.session_state.get("form_claim"), st.session_state.get("form_bill")
        if ok and upload:
            claim = {"claim_id": f"CLM-NEW-{len(results) + 1}", "policy_no": policy_no, "claimant_name": name,
                     "claim_reason": reason, "medical_facility": facility, "admission_date": admit.isoformat(),
                     "discharge_date": discharge.isoformat(), "claimed_amount_inr": str(claimed),
                     "submitted_date": submitted.isoformat(), "documents_provided": ";".join(docs), "bill_file": upload.name}
            bill_text = core.read_pdf(upload)
            st.session_state["form_claim"], st.session_state["form_bill"] = claim, bill_text
        elif ok:
            st.warning("Please upload the bill PDF.")
        if not bill_text:
            st.info("Fill in the form and upload a bill to continue.")
    if bill_text:
        with st.expander("Bill text read from the PDF"):
            st.code(bill_text)
        if st.button("Assess this claim", type="primary", disabled=llm is None or not claim):
            with st.spinner("Reading bill → checking → applying rules → writing report…"):
                results[claim["claim_id"]] = core.process_claim(llm, data, index, claim, queue, bill_text=bill_text)
                st.session_state["last"] = claim["claim_id"]
            st.success("Done. Open the **Assessment** tab.")

with tab_result:
    if not results:
        st.info("Assess a claim first.")
    else:
        cid = st.selectbox("Claim", list(results), index=list(results).index(st.session_state.get("last", list(results)[0])))
        r = results[cid]
        colour = {"APPROVE": "green", "PARTIAL_APPROVAL": "orange", "REJECT": "red", "NEEDS_REVIEW": "blue"}[r["verdict"]]
        st.markdown(f"### Decision: :{colour}[{r['verdict'].replace('_', ' ')}]")
        if r.get("settlement"):
            s = r["settlement"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Claimed", f"₹{s['claimed']:,.0f}")
            c2.metric("Admissible", f"₹{s['admissible']:,.0f}")
            c3.metric("Co-payment", f"₹{s['copay']:,.0f}")
            c4.metric("Payable", f"₹{core.payable_for(r['verdict'], s):,.0f}")
        st.markdown("**Rule checks** (decided by code)")
        st.dataframe(pd.DataFrame(r["findings"]), width="stretch", hide_index=True)
        if r.get("settlement") and r["settlement"]["deductions"]:
            st.markdown("**Deductions**")
            st.dataframe(pd.DataFrame(r["settlement"]["deductions"]), width="stretch", hide_index=True)
        if r.get("extraction_problems"):
            for p in r["extraction_problems"]:
                st.warning("Bill reading: " + p)
        with st.expander("Model's coverage opinion (second opinion only)"):
            st.json(r.get("opinion", {}))
        st.markdown("**Assessment report** (written by the model)")
        show_flags(r.get("text_flags", []))
        st.markdown(r.get("report", ""))
        with st.expander("Letter to the member"):
            st.text(r.get("letter", ""))
        if r.get("agent"):
            st.markdown("**Investigator's brief**")
            st.write(r["agent"]["answer"])
            show_trace(r["agent"]["trace"])

with tab_chat:
    q = st.text_input("Member question", "Is cataract surgery covered in my first year?")
    if st.button("Ask the handbook", disabled=llm is None):
        ans = core.ask_handbook(llm, data, index, q)
        st.write(ans["answer"])
        if ans["unknown_clauses"]:
            st.warning(f"The answer cites clauses that don't exist: {ans['unknown_clauses']}")
        show_trace(ans["trace"])

with tab_queue:
    render_queue(queue, approver,
                 executors={"settlement": core.record_decision(DATA_DIR), "rejection": core.record_decision(DATA_DIR),
                            "investigation": lambda p: "investigation opened"},
                 editable={"settlement": "member_letter", "rejection": "member_letter", "investigation": "investigation_brief"})

with tab_audit:
    render_audit(queue)

with tab_data:
    st.markdown("**Policyholders**")
    st.dataframe(pd.DataFrame(data["policies"].values()), width="stretch", hide_index=True)
    st.markdown("**Past claims**")
    st.dataframe(pd.DataFrame(data["past_claims"]), width="stretch", hide_index=True)
    st.markdown("**Member handbook**")
    for c in data["clauses"]:
        st.markdown(f"**Clause {c['clause']} · {c['title']}**  \n{c['text']}")
    with open(os.path.join(DATA_DIR, "member_handbook.pdf"), "rb") as fh:
        st.download_button("Download the handbook PDF", fh, "member_handbook.pdf")
