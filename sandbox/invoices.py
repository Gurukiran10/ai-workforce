"""Render fake vendor invoices as real PDF files (fpdf2)."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF


def inr(x: float) -> str:
    """Indian digit grouping: 185000.0 -> '1,85,000.00'."""
    whole, frac = f"{x:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{whole}.{frac}"


def render_invoice_pdf(spec: dict, path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, spec["vendor"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "GSTIN 29ABCDE1234F1Z5  |  billing@" + spec["vendor"].split()[0].lower() + ".example", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "TAX INVOICE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, f"Invoice No: {spec['invoice_no']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Invoice Date: {spec['invoice_date']}", new_x="LMARGIN", new_y="NEXT")
    if spec.get("due_date"):
        pdf.cell(0, 6, f"Payment Due: {spec['due_date']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Bill To: Acme Logistics Pvt Ltd, Bengaluru", new_x="LMARGIN", new_y="NEXT")
    if spec.get("note"):
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, spec["note"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(110, 7, "Description", border=1)
    pdf.cell(20, 7, "Qty", border=1)
    pdf.cell(50, 7, "Amount (INR)", border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    subtotal = 0.0
    for desc, qty, price in spec["lines"]:
        amt = qty * price
        subtotal += amt
        pdf.cell(110, 7, desc, border=1)
        pdf.cell(20, 7, str(qty), border=1)
        pdf.cell(50, 7, inr(amt), border=1, new_x="LMARGIN", new_y="NEXT")
    gst = subtotal * spec["gst_rate"]
    total = round(subtotal + gst, 2)
    pdf.cell(130, 7, "Subtotal", border=1)
    pdf.cell(50, 7, inr(subtotal), border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.cell(130, 7, f"GST @ {int(spec['gst_rate'] * 100)}%", border=1)
    pdf.cell(50, 7, inr(gst), border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(130, 8, "TOTAL PAYABLE", border=1)
    pdf.cell(50, 8, "INR " + inr(total), border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, "Payment to the bank account on file with Acme Logistics. This is a computer generated invoice.")
    pdf.output(str(path))
