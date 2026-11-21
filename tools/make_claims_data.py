"""Generates the fictional sample data for project 11 (insurance claims). Run from the repo root:
    python tools/make_claims_data.py
"""
import csv
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "p11_claim_automation", "data")
INSURER = "Nirbhay Health Insurance Co. (fictional)"

HANDBOOK = [
    ("1", "About this handbook", "This handbook explains what the Nirbhay Family Health Plan covers, what it does not cover, and how to make a claim. Clause numbers are used in all claim decisions."),
    ("2.1", "In-patient hospitalisation", "We pay reasonable and customary medical expenses for hospitalisation of at least 24 hours for an illness or injury, up to the sum insured, subject to the limits, waiting periods and exclusions in this handbook."),
    ("2.2", "Day-care procedures", "Procedures that need less than 24 hours of hospitalisation because of medical technology, such as cataract surgery, are covered as day-care treatment, subject to the waiting periods in clause 3."),
    ("2.3", "Pre- and post-hospitalisation", "Medical expenses incurred up to 30 days before admission and up to 60 days after discharge for the same illness are covered."),
    ("3.1", "Initial waiting period", "No claim is payable for illness that starts within the first 30 days of the policy start date. This waiting period does not apply to accidents."),
    ("3.2", "Specific disease waiting period", "The following are covered only after 24 months of continuous cover: cataract, hernia, joint replacement, kidney stones (renal calculi), sinusitis, piles (haemorrhoids) and tonsillectomy."),
    ("3.3", "Pre-existing diseases", "Conditions declared as pre-existing at the time of proposal are covered only after 36 months of continuous cover."),
    ("4.1", "General exclusions", "We do not pay for treatment of: (a) HIV/AIDS and related illness; (b) Alzheimer's disease and other dementia; (c) Parkinson's disease; (d) pregnancy, childbirth and maternity, unless the maternity add-on was bought; (e) alcohol or substance abuse and de-addiction; (f) self-inflicted injuries; (g) sexually transmitted diseases; (h) cosmetic or aesthetic treatment; (i) infertility treatment; (j) experimental or unproven treatment."),
    ("5.1", "Room rent limit", "Room rent, boarding and nursing are payable up to 1% of the sum insured per day. Any amount above this limit is not payable."),
    ("5.2", "Co-payment for senior members", "For an insured person aged 60 or above at the time of admission, 10% of the admissible claim amount is paid by the insured person (co-payment)."),
    ("5.3", "Non-payable items", "Consumables such as gloves, masks, PPE kits and toiletries, registration and admission fees, attendant food and other administrative charges are not payable."),
    ("6.1", "Documents required", "For a reimbursement claim, submit: the completed claim form, original hospital bills with itemised breakup, discharge summary, prescriptions and investigation reports, and photo ID of the insured person."),
    ("6.2", "Time limit", "Reimbursement claims must be submitted within 30 days of discharge. Late claims may be accepted only with a written reason and the approval of a claims manager."),
    ("6.3", "Claim decisions", "Every rejection or partial payment is reviewed and signed by a claims officer, and the member is told the clause used and how to ask for a review."),
    ("6.4", "Amount claimed", "The amount claimed cannot be more than the total of the original itemised bills. A claim for more than the bills is rejected and may be investigated under clause 7.1."),
    ("7.1", "Fraud", "Claims using duplicate, altered or forged bills, or bills for a different person, are investigated. Confirmed fraud leads to rejection and cancellation of the policy."),
]

POLICIES = [  # policy_no, member_name, age, sum_insured, start, claimed_so_far, pre_existing
    ("NHP-1001", "Anil Deshmukh", 45, 500000, "2023-04-01", 0, ""),
    ("NHP-1002", "Sunita Rao", 38, 300000, "2024-01-15", 12000, ""),
    ("NHP-1003", "Ramesh Iyer", 71, 500000, "2022-06-01", 0, "hypertension"),
    ("NHP-1004", "Meera Kapoor", 58, 500000, "2025-08-10", 0, ""),
    ("NHP-1005", "Vikram Singh", 42, 500000, "2024-03-01", 0, ""),
    ("NHP-1006", "Farah Ali", 35, 300000, "2023-09-01", 28600, ""),
    ("NHP-1007", "Gopal Menon", 66, 500000, "2021-01-01", 40000, "diabetes"),
]

PAST = [("CLM-0811", "NHP-1002", "SNH-2026-1140", 12000, "Paid", "2026-03-12"),
        ("CLM-0902", "NHP-1006", "HB-2026-0912", 28600, "Paid", "2026-09-20"),
        ("CLM-0870", "NHP-1007", "RMH-2026-0507", 40000, "Paid", "2026-05-22")]

ALL_DOCS = "claim form;original bills;discharge summary;prescriptions and investigation reports;photo ID"

# claim_id, policy_no, claimant, reason, facility, admit, discharge, claimed, submitted, docs, bill
CLAIMS = [
    ("CLM-1101", "NHP-1001", "Anil Deshmukh", "Dengue fever", "City Care Hospital, Pune", "2026-10-20", "2026-10-24", 37200, "2026-10-29", ALL_DOCS),
    ("CLM-1102", "NHP-1002", "Sunita Rao", "Acute gastroenteritis", "Sahyadri Nursing Home, Pune", "2026-10-11", "2026-10-13", 24000, "2026-10-20", ALL_DOCS),
    ("CLM-1103", "NHP-1003", "Ramesh Iyer", "Memory loss and confusion", "Lotus Neuro Centre, Bengaluru", "2026-09-28", "2026-10-03", 62500, "2026-10-10", ALL_DOCS),
    ("CLM-1104", "NHP-1004", "Meera Kapoor", "Blurred vision, right eye surgery", "Clearsight Eye Hospital, Mumbai", "2026-10-05", "2026-10-05", 45000, "2026-10-12", ALL_DOCS),
    ("CLM-1105", "NHP-1005", "Vikram Singh", "Severe abdominal pain, emergency surgery", "Metro Multispeciality Hospital, Nagpur", "2026-10-28", "2026-10-31", 118000, "2026-11-06",
     "claim form;original bills;prescriptions and investigation reports;photo ID"),
    ("CLM-1106", "NHP-1006", "Farah Ali", "Typhoid fever", "Hope Bay Hospital, Goa", "2026-09-02", "2026-09-06", 28600, "2026-11-10", ALL_DOCS),
    ("CLM-1107", "NHP-1007", "Gopal Menon", "Pneumonia", "Riverside Medical Hospital, Kochi", "2026-10-15", "2026-10-20", 82500, "2026-10-27", ALL_DOCS),
]

# bill file -> (hospital, bill_no, patient_name_on_bill, age, admit, discharge, diagnosis, lines[(item, category, qty, rate)])
BILLS = {
    "CLM-1101": ("City Care Hospital, Pune", "CCH-2026-4471", "Anil Deshmukh", 45, "2026-10-20", "2026-10-24", "Dengue fever with thrombocytopenia",
                 [("Semi-private room (per day)", "Room", 4, 3500), ("Physician consultation", "Doctor", 1, 6000),
                  ("Medicines and IV fluids", "Medicines", 1, 9800), ("Platelet count, NS1 antigen, CBC", "Investigations", 1, 7400)]),
    "CLM-1102": ("Sahyadri Nursing Home, Pune", "SNH-2026-1882", "Sunita Rao", 38, "2026-10-11", "2026-10-13", "Acute gastroenteritis with dehydration",
                 [("General ward (per day)", "Room", 2, 2200), ("Physician consultation", "Doctor", 1, 3000),
                  ("Medicines and IV fluids", "Medicines", 1, 6800), ("Stool and blood tests", "Investigations", 1, 4200)]),
    "CLM-1103": ("Lotus Neuro Centre, Bengaluru", "LNC-2026-0318", "Ramesh Iyer", 71, "2026-09-28", "2026-10-03", "Alzheimer's disease, moderate stage",
                 [("Private room (per day)", "Room", 5, 4500), ("Neurologist consultation", "Doctor", 1, 9000),
                  ("Medicines", "Medicines", 1, 14000), ("MRI brain and cognitive assessment", "Investigations", 1, 17000)]),
    "CLM-1104": ("Clearsight Eye Hospital, Mumbai", "CEH-2026-2290", "Meera Kapoor", 58, "2026-10-05", "2026-10-05", "Senile cataract, right eye (phacoemulsification with IOL)",
                 [("Day-care bed", "Room", 1, 2500), ("Surgeon fee", "Doctor", 1, 15000),
                  ("Intraocular lens and surgery package", "Procedure", 1, 26000), ("Pre-operative tests", "Investigations", 1, 1500)]),
    "CLM-1105": ("Metro Multispeciality Hospital, Nagpur", "MMH-2026-7731", "Vikas Singh", 42, "2026-10-28", "2026-10-31", "Acute appendicitis (laparoscopic appendectomy)",
                 [("Twin-sharing room (per day)", "Room", 3, 4000), ("Surgeon and anaesthetist fees", "Doctor", 1, 38000),
                  ("Operation theatre and procedure", "Procedure", 1, 42000), ("Medicines", "Medicines", 1, 14000),
                  ("Investigations and ultrasound", "Investigations", 1, 12000)]),
    "CLM-1106": ("Hope Bay Hospital, Goa", "HB-2026-0912", "Farah Ali", 35, "2026-09-02", "2026-09-06", "Typhoid fever",
                 [("Semi-private room (per day)", "Room", 4, 3000), ("Physician consultation", "Doctor", 1, 5000),
                  ("Medicines and IV fluids", "Medicines", 1, 7400), ("Widal test, blood culture", "Investigations", 1, 4200)]),
    "CLM-1107": ("Riverside Medical Hospital, Kochi", "RMH-2026-1164", "Gopal Menon", 66, "2026-10-15", "2026-10-20", "Community-acquired pneumonia",
                 [("Private room (per day)", "Room", 5, 7000), ("Pulmonologist consultation", "Doctor", 1, 12000),
                  ("Medicines and nebulisation", "Medicines", 1, 21500), ("Chest X-ray, CT and blood tests", "Investigations", 1, 9800),
                  ("Gloves, masks and PPE kits", "Consumables", 1, 3200), ("Registration and admission fee", "Admin", 1, 1000)]),
}


def write_csv(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def handbook_pdf(path):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4, title="Member handbook")
    story = [Paragraph(f"{INSURER}<br/>Family Health Plan: Member Handbook 2026-27", styles["Title"]), Spacer(1, 12)]
    for cid, title, text in HANDBOOK:
        story += [Paragraph(f"Clause {cid}. {title}", styles["Heading3"]), Paragraph(text, styles["BodyText"]), Spacer(1, 6)]
    doc.build(story)


def bill_pdf(path, b):
    hospital, bill_no, name, age, admit, discharge, diagnosis, lines = b
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, 800, hospital)
    c.setFont("Courier", 10)
    rows = ["FINAL HOSPITAL BILL (fictional sample)", "",
            f"Bill No: {bill_no}", f"Patient Name: {name}    Age: {age}",
            f"Admission: {admit}    Discharge: {discharge}", f"Diagnosis: {diagnosis}", "",
            f"{'Item':<38}{'Category':<14}{'Qty':>4}{'Rate':>10}{'Amount':>11}", "-" * 77]
    total = 0
    for item, cat, qty, rate in lines:
        total += qty * rate
        rows.append(f"{item[:37]:<38}{cat:<14}{qty:>4}{rate:>10,}{qty * rate:>11,}")
    rows += ["-" * 77, f"{'TOTAL AMOUNT (INR)':<66}{total:>11,}", "", "This is a computer-generated bill."]
    y = 770
    for r in rows:
        c.drawString(50, y, r)
        y -= 15
    c.save()
    return total


if __name__ == "__main__":
    os.makedirs(os.path.join(OUT, "bills"), exist_ok=True)
    handbook_pdf(os.path.join(OUT, "member_handbook.pdf"))
    write_csv("policyholders.csv", ["policy_no", "member_name", "age", "sum_insured_inr", "policy_start",
                                    "claimed_so_far_inr", "pre_existing_declared"], POLICIES)
    write_csv("past_claims.csv", ["claim_id", "policy_no", "bill_no", "amount_inr", "status", "paid_date"], PAST)
    write_csv("claims.csv", ["claim_id", "policy_no", "claimant_name", "claim_reason", "medical_facility",
                             "admission_date", "discharge_date", "claimed_amount_inr", "submitted_date",
                             "documents_provided", "bill_file"],
              [c + (f"bills/{c[0]}.pdf",) for c in CLAIMS])
    for cid, b in BILLS.items():
        print(cid, "bill total", bill_pdf(os.path.join(OUT, "bills", f"{cid}.pdf"), b))
