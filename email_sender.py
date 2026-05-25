import io
import json
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


def _readable_text(value):
    """
    Convert GPT JSON/dict values into complete readable text.

    For fields like top_strength and biggest_improvement_area, GPT may return:
    {
      "summary": "...",
      "by_parameter": {"guardrails": "...", "opening": "..."}
    }

    This function shows BOTH summary and all parameter-wise details.
    """
    if value is None:
        return ""

    if isinstance(value, dict):
        lines = []

        summary = value.get("summary")
        if summary:
            lines.append(str(summary).strip())

        by_parameter = value.get("by_parameter")
        if isinstance(by_parameter, dict) and by_parameter:
            if lines:
                lines.append("")
            lines.append("Parameter-wise details:")

            preferred_order = [
                "guardrails",
                "opening",
                "discovery",
                "evidence",
                "personal_urgency",
                "real_hesitation_reason",
                "clear_next_step",
            ]

            used = set()
            for key in preferred_order:
                if key in by_parameter:
                    label = key.replace("_", " ").title()
                    detail = str(by_parameter[key]).strip()
                    lines.append(f"- {label}: {detail}")
                    used.add(key)

            for key, detail in by_parameter.items():
                if key not in used:
                    label = str(key).replace("_", " ").title()
                    lines.append(f"- {label}: {str(detail).strip()}")

        if lines:
            return "\n".join(lines)

        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, list):
        return "\n".join(_readable_text(item) for item in value)

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
                return _readable_text(parsed)
            except Exception:
                return value
        return value

    return str(value)


def _batch_summary(results: List[Dict]) -> Dict[str, float | int | str]:
    total = len(results)
    full_analysis = [r for r in results if r.get("call_type") == "full_analysis"]
    follow_up_only = [r for r in results if r.get("call_type") == "follow_up_only"]
    not_worthy = [r for r in results if not r.get("analysis_worthy")]

    converted_count = sum(1 for r in full_analysis if r.get("converted_status") == "Converted")
    not_converted_count = len(full_analysis) - converted_count

    percentages = []
    for r in full_analysis + follow_up_only:
        pct = _percent_to_float(r.get("overall_percentage"))
        if pct is not None:
            percentages.append(pct)

    avg_score = round(sum(percentages) / len(percentages), 2) if percentages else None

    return {
        "total": total,
        "full_analysis": len(full_analysis),
        "follow_up_only": len(follow_up_only),
        "not_worthy": len(not_worthy),
        "converted": converted_count,
        "not_converted": not_converted_count,
        "average_score": avg_score,
    }


def _score_parameter_wise(row: Dict) -> str:
    if not row.get("analysis_worthy"):
        return "Not Worthy"

    parts = [
        f"Guardrails: {row.get('guardrails', '')}",
        f"Opening: {row.get('opening_score', '')}/10" if row.get("opening_score") else "Opening: ",
        f"Discovery: {row.get('discovery_score', '')}/10" if row.get("discovery_score") else "Discovery: ",
        f"Evidence: {row.get('evidence_score', '')}/10" if row.get("evidence_score") else "Evidence: ",
        f"Personal Urgency: {row.get('personal_urgency_score', '')}/10" if row.get("personal_urgency_score") else "Personal Urgency: ",
        f"Real Hesitation Reason: {row.get('real_hesitation_reason_score', '')}",
        f"Clear Next Step: {row.get('clear_next_step_score', '')}/10" if row.get("clear_next_step_score") else "Clear Next Step: ",
    ]
    return "\n".join(parts)


def build_excel(results: List[Dict]) -> bytes:
    """Build an Excel file from expanded result rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Call Scores"

    headers = [
        "Date",
        "Student Number",
        "Call Type",
        "Call Recording Link",
        "Converted Status",
        "Overall Score",
        "Score Parameter Wise",
        "Top Strength",
        "Biggest Improvement Area",
        "Coaching Note",

        "Transcript Link",
        "Analysis Status",

        "Guardrails",
        "Guardrails Reason",
        "False Information Flagged",
        "False Information Detail",

        "Opening Score",
        "Opening - What Student Partner Said Right After Intro",
        "Opening Quote",
        "Opening Specific To Trial Activity",
        "Opening Why This Score",

        "Discovery Score",
        "Discovery Questions Asked",
        "Discovery What Student Partner Found Out",
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

        "Personal Urgency Score",
        "Personal Urgency Source Of Urgency",
        "Personal Urgency Student Situation Used",
        "Personal Urgency Quote",
        "Personal Urgency Why This Score",

        "Real Hesitation Reason Score",
        "Real Hesitation Reason N/A",
        "Real Hesitation Reason Objection Raised",
        "Real Hesitation Reason Surface Reason",
        "Real Hesitation Reason Real Reason Found",
        "Real Hesitation Reason Quote",
        "Real Hesitation Reason Why This Score",

        "Clear Next Step Score",
        "Clear Next Step What Happened At End",
        "Clear Next Step Payment Link Sent",
        "Clear Next Step Follow-up Date/Time Agreed",
        "Clear Next Step WhatsApp Details Sent",
        "Clear Next Step Quote",
        "Clear Next Step Why This Score",
    ]

    keys = [
        "created_at",
        "student_number",
        "call_type",
        "call_audio_link",
        "converted_status",
        "overall_score",
        "__score_parameter_wise",
        "top_strength",
        "biggest_improvement_area",
        "coaching_note",

        "call_transcript_link",
        "analysis_worthy",

        "guardrails",
        "guardrails_reason",
        "guardrails_false_information_flagged",
        "guardrails_false_information_detail",

        "opening_score",
        "opening_what_student_partner_said_right_after_intro",
        "opening_quote",
        "opening_specific_to_student_trial_activity",
        "opening_why_this_score",

        "discovery_score",
        "discovery_questions_asked_by_student_partner",
        "discovery_what_student_partner_found_out",
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

        "personal_urgency_score",
        "personal_urgency_source_of_urgency",
        "personal_urgency_student_situation_used",
        "personal_urgency_quote",
        "personal_urgency_why_this_score",

        "real_hesitation_reason_score",
        "real_hesitation_reason_na",
        "real_hesitation_reason_objection_raised_by_student",
        "real_hesitation_reason_surface_reason_stated",
        "real_hesitation_reason_real_reason_found",
        "real_hesitation_reason_quote_of_attempt",
        "real_hesitation_reason_why_this_score",

        "clear_next_step_score",
        "clear_next_step_what_happened_at_end",
        "clear_next_step_payment_link_sent",
        "clear_next_step_followup_date_and_time_agreed",
        "clear_next_step_course_details_sent_on_whatsapp",
        "clear_next_step_quote_of_closing_line",
        "clear_next_step_why_this_score",
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
            if key == "__score_parameter_wise":
                value = _score_parameter_wise(row)
            else:
                value = row.get(key, "")

            if key == "created_at":
                value = str(value)[:10]
            elif key == "analysis_worthy":
                value = "Yes" if value else "Not Worthy"
            elif key not in {"call_audio_link", "call_transcript_link"}:
                value = _readable_text(value)

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
- Full analysis calls: {summary['full_analysis']}
- Follow-up only calls: {summary['follow_up_only']}
- Not worthy calls: {summary['not_worthy']}
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
