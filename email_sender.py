import io
import os
import re
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


def _percent_to_float(value) -> float | None:
    if value is None:
        return None
    text = str(value)
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))


def _batch_summary(results: List[Dict]) -> Dict[str, float | int | str]:
    total = len(results)
    worthy = [r for r in results if r.get("analysis_worthy")]
    not_worthy_count = total - len(worthy)

    converted_count = sum(1 for r in worthy if r.get("converted_status") == "Converted")
    not_converted_count = len(worthy) - converted_count

    percentages = []
    for r in worthy:
        pct = _percent_to_float(r.get("overall_percentage"))
        if pct is not None:
            percentages.append(pct)

    avg_score = round(sum(percentages) / len(percentages), 2) if percentages else None

    return {
        "total": total,
        "analysis_worthy": len(worthy),
        "not_analysis_worthy": not_worthy_count,
        "converted": converted_count,
        "not_converted": not_converted_count,
        "average_score": avg_score,
    }


def build_excel(results: List[Dict]) -> bytes:
    """
    Build an Excel file from expanded result rows.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Call Scores"

    headers = [
        "Date",
        "Student Number",
        "Call Recording Link",
        "Transcript Link",
        "Converted Status",
        "Analysis Worthy",

        "Guardrails",
        "Guardrails Reason",
        "False Information Flagged",
        "False Information Detail",

        "Opening Score",
        "Opening - What Agent Said Right After Intro",
        "Opening Quote",
        "Opening Specific To Trial Activity",
        "Opening Why This Score",

        "Discovery Score",
        "Discovery Questions Asked",
        "Discovery What Agent Found Out",
        "Discovery Student Said Own Problem",
        "Discovery Best Moment Quote",
        "Discovery Why This Score",

        "Evidence Score",
        "Evidence Discovery Finding Used",
        "Evidence Master Course Feature Connected",
        "Evidence Factually Accurate",
        "Evidence Inaccuracy Detail",
        "Evidence Quote",
        "Evidence Why This Score",

        "Resonance Score",
        "Resonance Source Of Urgency",
        "Resonance Student Situation Used",
        "Resonance Quote",
        "Resonance Why This Score",

        "Diagnosis Score",
        "Diagnosis N/A",
        "Diagnosis Objection Raised",
        "Diagnosis Surface Reason",
        "Diagnosis Real Reason Found",
        "Diagnosis Quote",
        "Diagnosis Why This Score",

        "Closure Score",
        "Closure What Happened At End",
        "Closure Payment Link Sent",
        "Closure Follow-up Date/Time Agreed",
        "Closure WhatsApp Details Sent",
        "Closure Quote",
        "Closure Why This Score",

        "Overall Score",
        "Overall Percentage",
        "Guardrails Review Flag",

        "Top Strength",
        "Biggest Improvement Area",
        "Coaching Note",
    ]

    keys = [
        "created_at",
        "student_number",
        "call_audio_link",
        "call_transcript_link",
        "converted_status",
        "analysis_worthy",

        "guardrails",
        "guardrails_reason",
        "guardrails_false_information_flagged",
        "guardrails_false_information_detail",

        "opening_score",
        "opening_what_agent_said_right_after_intro",
        "opening_quote",
        "opening_specific_to_student_trial_activity",
        "opening_why_this_score",

        "discovery_score",
        "discovery_questions_asked_by_agent",
        "discovery_what_agent_found_out",
        "discovery_student_said_own_problem_out_loud",
        "discovery_best_discovery_moment_quote",
        "discovery_why_this_score",

        "evidence_score",
        "evidence_discovery_finding_used",
        "evidence_master_course_feature_connected",
        "evidence_factually_accurate_about_master_course",
        "evidence_inaccuracy_detail",
        "evidence_quote",
        "evidence_why_this_score",

        "resonance_score",
        "resonance_source_of_urgency",
        "resonance_student_situation_used",
        "resonance_quote",
        "resonance_why_this_score",

        "diagnosis_score",
        "diagnosis_na",
        "diagnosis_objection_raised_by_student",
        "diagnosis_surface_reason_stated",
        "diagnosis_real_reason_found",
        "diagnosis_quote_of_diagnosis_attempt",
        "diagnosis_why_this_score",

        "closure_score",
        "closure_what_happened_at_end",
        "closure_payment_link_sent",
        "closure_followup_date_and_time_agreed",
        "closure_course_details_sent_on_whatsapp",
        "closure_quote_of_closing_line",
        "closure_why_this_score",

        "overall_score",
        "overall_percentage",
        "guardrails_review_flag",

        "top_strength",
        "biggest_improvement_area",
        "coaching_note",
    ]

    header_fill = PatternFill("solid", fgColor="E24B4A")
    header_font = Font(bold=True, color="FFFFFF")

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_idx, row in enumerate(results, 2):
        for col_idx, key in enumerate(keys, 1):
            value = row.get(key, "")

            if key == "created_at":
                value = str(value)[:10]
            elif key == "analysis_worthy":
                value = "Yes" if value else "Not Analysis Worthy"

            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)

            if key in {"call_audio_link", "call_transcript_link"} and value:
                cell.hyperlink = value
                cell.style = "Hyperlink"

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for col in ws.columns:
        max_len = max((len(str(c.value)) if c.value else 0) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 4, 12), 60)

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


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

    excel_bytes = build_excel(results)
    summary = _batch_summary(results)

    avg_text = (
        f"{summary['average_score']}%"
        if summary["average_score"] is not None
        else "Not available"
    )

    body = f"""Hi,

Please find attached the EduTap EPFO call scoring report for {batch_label}.

Summary:
- Total calls processed: {summary['total']}
- Analysis worthy calls: {summary['analysis_worthy']}
- Not analysis worthy calls: {summary['not_analysis_worthy']}
- Converted calls: {summary['converted']}
- Not converted calls: {summary['not_converted']}
- Average score: {avg_text}

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
