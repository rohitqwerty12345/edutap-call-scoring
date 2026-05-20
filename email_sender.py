import io
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

import openpyxl
from dotenv import load_dotenv
from openpyxl.styles import Alignment, Font, PatternFill

load_dotenv()


def get_setting(name: str, default: str | None = None) -> str | None:
    """Read from environment first, then Streamlit secrets if available."""
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass

    return default


def build_excel(results: List[Dict]) -> bytes:
    """
    Build an Excel file from result rows.
    Returns bytes of the .xlsx file.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Call Scores"

    headers = [
        "Student Number",
        "Date",
        "Analysis Worthy",
        "Guardrails",
        "Opening",
        "Discovery",
        "Evidence",
        "Resonance",
        "Diagnosis",
        "Closure",
        "Overall Score",
        "Top Strength",
        "Biggest Improvement Area",
        "Coaching Note",
    ]

    header_fill = PatternFill("solid", fgColor="E24B4A")
    header_font = Font(bold=True, color="FFFFFF")

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_idx, row in enumerate(results, 2):
        if not row.get("analysis_worthy"):
            values = [
                row.get("student_number", ""),
                str(row.get("created_at", ""))[:10],
                "Not Analysis Worthy",
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
            ]
        else:
            values = [
                row.get("student_number", ""),
                str(row.get("created_at", ""))[:10],
                "Yes",
                row.get("guardrails", ""),
                row.get("opening_score", ""),
                row.get("discovery_score", ""),
                row.get("evidence_score", ""),
                row.get("resonance_score", ""),
                row.get("diagnosis_score", ""),
                row.get("closure_score", ""),
                row.get("overall_score", ""),
                row.get("top_strength", ""),
                row.get("biggest_improvement_area", ""),
                row.get("coaching_note", ""),
            ]

        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 4, 12), 55)

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def send_report(results: List[Dict], batch_label: str = "Today") -> None:
    """
    Build Excel and send it to all recipient emails.
    """
    sender = get_setting("SENDER_EMAIL")
    password = get_setting("SENDER_PASSWORD")
    recipients_raw = get_setting("RECIPIENT_EMAILS", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not sender:
        raise RuntimeError("SENDER_EMAIL is missing.")
    if not password:
        raise RuntimeError("SENDER_PASSWORD is missing. Use a Gmail App Password, not your normal Gmail password.")
    if not recipients:
        raise RuntimeError("RECIPIENT_EMAILS is missing.")

    excel_bytes = build_excel(results)

    worthy_count = sum(1 for r in results if r.get("analysis_worthy"))
    not_worthy_count = len(results) - worthy_count

    body = f"""Hi,

Please find attached the EduTap EPFO call scoring report for {batch_label}.

Summary:
- Total calls processed: {len(results)}
- Analysis worthy calls: {worthy_count}
- Not analysis worthy: {not_worthy_count}

The attached Excel file contains individual scores for each call including:
- Guardrails (Pass/Fail)
- Opening, Discovery, Evidence, Resonance, Diagnosis, Closure scores
- Overall score and percentage
- Top strength, biggest improvement area, and coaching note for each agent

Regards,
EduTap Call Scoring System
"""

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"EduTap Call Scores - {batch_label}"
    msg.attach(MIMEText(body, "plain"))

    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(excel_bytes)
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        f"attachment; filename=EduTap_Call_Scores_{batch_label.replace(' ', '_')}.xlsx",
    )
    msg.attach(attachment)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
