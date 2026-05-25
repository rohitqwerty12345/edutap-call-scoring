import csv
import io
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()

EMAIL_COLUMNS = [
    "Call Recording Link",
    "Average Score",
    "Score Parameter Wise",
    "Strengths",
    "Improvement Areas",
    "Learnings",
]


def get_setting(name: str, default: str | None = None) -> str | None:
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


def build_csv(results: List[Dict]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EMAIL_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in results:
        writer.writerow({col: row.get(col, "") for col in EMAIL_COLUMNS})
    return output.getvalue().encode("utf-8-sig")


def _batch_summary(results: List[Dict]) -> Dict[str, int]:
    return {
        "total": len(results),
        "full_analysis": sum(1 for r in results if r.get("Call Type") == "full_analysis"),
        "follow_up_only": sum(1 for r in results if r.get("Call Type") == "follow_up_only"),
        "not_worthy": sum(1 for r in results if r.get("Call Type") == "not_worthy"),
        "converted": sum(1 for r in results if r.get("Converted Status") == "Converted"),
    }


def send_report(results: List[Dict], batch_label: str = "Today") -> None:
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

    csv_bytes = build_csv(results)
    summary = _batch_summary(results)

    body = f"""Hi,

Please find attached the EduTap EPFO call scoring report for {batch_label}.

Summary:
- Total calls processed: {summary['total']}
- Full analysis calls: {summary['full_analysis']}
- Follow-up only calls: {summary['follow_up_only']}
- Not worthy calls: {summary['not_worthy']}
- Converted calls: {summary['converted']}

Regards,
EduTap Call Scoring System
"""

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"EduTap Call Scores - {batch_label}"
    msg.attach(MIMEText(body, "plain"))

    attachment = MIMEBase("text", "csv")
    attachment.set_payload(csv_bytes)
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        f"attachment; filename=EduTap_Call_Scores_{batch_label.replace(' ', '_')}.csv",
    )
    msg.attach(attachment)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
