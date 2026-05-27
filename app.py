import html
import json
import os
from datetime import date
from typing import Any

import requests

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from email_sender import send_error_report
from pipeline import extract_student_number
from supabase_client import enqueue_call_batch, fetch_all_results, fetch_recent_batches

load_dotenv()


def get_setting(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


DASHBOARD_PASSWORD = get_setting("DASHBOARD_PASSWORD", "show123")

GITHUB_WORKFLOW_TIMEOUT_TEXT = (
    "Upload successful, but backend processing could not be started automatically. "
    "The files are safely queued and will be picked up by the scheduled backend run. "
    "The admin has been notified. You can close this window."
)


def _trigger_github_worker() -> tuple[bool, str]:
    """Trigger the GitHub Actions worker after a successful upload."""
    token = get_setting("GITHUB_ACTIONS_TOKEN")
    owner = get_setting("GITHUB_REPO_OWNER", "rohitqwerty12345")
    repo = get_setting("GITHUB_REPO_NAME", "edutap-call-scoring")
    workflow_file = get_setting("GITHUB_WORKFLOW_FILE", "process-calls.yml")
    ref = get_setting("GITHUB_WORKFLOW_REF", "main")

    if not token:
        return False, "GITHUB_ACTIONS_TOKEN is missing in Streamlit Secrets."
    if not owner or not repo or not workflow_file or not ref:
        return False, "GitHub workflow trigger settings are incomplete."

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload: dict[str, Any] = {"ref": ref}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
    except Exception as exc:
        return False, f"Could not connect to GitHub Actions API: {exc}"

    if response.status_code == 204:
        return True, "GitHub Actions backend worker started."

    if response.status_code in {401, 403}:
        return False, "GitHub token does not have permission to start the workflow."
    if response.status_code == 404:
        return False, "GitHub repository or workflow file was not found, or token has no access."
    if response.status_code == 422:
        return False, "GitHub workflow could not be started. Check workflow_dispatch and branch name."

    return False, f"GitHub Actions returned status {response.status_code}: {response.text[:500]}"


FINAL_COLUMNS = [
    "Date",
    "Student Number",
    "Call Type",
    "Call Recording Link",
    "Converted Status",
    "Average Score",
    "Score Parameter Wise",
    "Strengths",
    "Improvement Areas",
    "Learnings",
    "Transcript Link",
]


def _simple_error_message(exc: Exception) -> str:
    text = str(exc or "").lower()

    if "supabase_url" in text or "supabase_key" in text:
        return "The database connection is not set up. Please contact the admin."
    if "storage" in text or "bucket" in text or "upload" in text:
        return "The call file could not be uploaded. Please contact the admin."
    if "database" in text or "relation" in text or "column" in text or "insert" in text:
        return "The upload entry could not be saved. Please contact the admin."
    if "sender_email" in text or "sender_password" in text or "recipient_emails" in text:
        return "The error email could not be sent. Please contact the admin."
    return "The files could not be uploaded. Please try again or contact the admin."


def _render_upload_overlay(placeholder, current: int, total: int) -> None:
    current = max(1, min(current, max(total, 1)))
    percent = (current / max(total, 1)) * 100
    placeholder.markdown(
        f"""
        <style>
        .edutap-processing-backdrop {{
            position: fixed;
            inset: 0;
            background: rgba(12, 17, 25, 0.76);
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(4px);
        }}
        .edutap-processing-box {{
            width: min(460px, 88vw);
            background: #ffffff;
            color: #111827;
            border-radius: 22px;
            padding: 36px 32px 34px;
            box-shadow: 0 24px 80px rgba(0,0,0,0.38);
            text-align: center;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        .edutap-spinner {{
            width: 58px;
            height: 58px;
            margin: 0 auto 18px;
            border-radius: 50%;
            border: 6px solid #fee2e2;
            border-top-color: #ef4444;
            animation: edutap-spin 0.9s linear infinite;
        }}
        @keyframes edutap-spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
        .edutap-processing-title {{
            font-size: 27px;
            line-height: 1.2;
            font-weight: 850;
            margin-bottom: 8px;
        }}
        .edutap-processing-subtitle {{
            font-size: 18px;
            color: #374151;
            margin-bottom: 22px;
        }}
        .edutap-processing-bar {{
            position: relative;
            width: 100%;
            height: 12px;
            background: #e5e7eb;
            border-radius: 999px;
            overflow: hidden;
        }}
        .edutap-processing-fill {{
            position: relative;
            height: 100%;
            width: {percent:.2f}%;
            min-width: 42px;
            background: linear-gradient(90deg, #dc2626 0%, #ef4444 45%, #fb7185 100%);
            border-radius: 999px;
            transition: width 300ms ease;
            overflow: hidden;
        }}
        .edutap-processing-fill::after {{
            content: "";
            position: absolute;
            inset: 0;
            width: 44%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.55), transparent);
            animation: edutap-shine 1.15s ease-in-out infinite;
        }}
        @keyframes edutap-shine {{
            from {{ transform: translateX(-120%); }}
            to {{ transform: translateX(260%); }}
        }}
        .edutap-processing-note {{
            margin-top: 16px;
            color: #6b7280;
            font-size: 14px;
        }}
        </style>
        <div class="edutap-processing-backdrop">
            <div class="edutap-processing-box">
                <div class="edutap-spinner"></div>
                <div class="edutap-processing-title">Uploading calls</div>
                <div class="edutap-processing-subtitle">Uploading {current} of {total}</div>
                <div class="edutap-processing-bar"><div class="edutap-processing-fill"></div></div>
                <div class="edutap-processing-note">Please wait. This usually takes only a few seconds.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_result_overlay(placeholder, message: str, message_type: str = "success") -> None:
    """Render final upload result as a fixed modal so the page does not feel jumpy after rerun."""
    is_error = message_type == "error"
    circle_color = "#ef4444" if is_error else "#16a34a"
    circle_bg = "#fee2e2" if is_error else "#dcfce7"
    icon = "!" if is_error else "✓"

    placeholder.markdown(
        f"""
        <style>
        .edutap-result-backdrop {{
            position: fixed;
            inset: 0;
            background: rgba(12, 17, 25, 0.76);
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(4px);
        }}
        .edutap-result-box {{
            width: min(520px, 88vw);
            background: #ffffff;
            color: #111827;
            border-radius: 22px;
            padding: 38px 34px;
            box-shadow: 0 24px 80px rgba(0,0,0,0.38);
            text-align: center;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            animation: edutap-result-pop 220ms ease-out;
        }}
        @keyframes edutap-result-pop {{
            from {{ opacity: 0; transform: translateY(10px) scale(0.98); }}
            to {{ opacity: 1; transform: translateY(0) scale(1); }}
        }}
        .edutap-result-icon {{
            width: 64px;
            height: 64px;
            margin: 0 auto 18px;
            border-radius: 50%;
            background: {circle_bg};
            color: {circle_color};
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 34px;
            font-weight: 900;
        }}
        .edutap-result-message {{
            font-size: 22px;
            line-height: 1.45;
            font-weight: 750;
            color: #111827;
        }}
        </style>
        <div class="edutap-result-backdrop">
            <div class="edutap-result-box">
                <div class="edutap-result-icon">{icon}</div>
                <div class="edutap-result-message">{html.escape(str(message))}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )



def _display_value(row, key, default=""):
    value = row.get(key, default)
    if value is None:
        return default

    text = str(value).strip()

    if key == "Date":
        if "T" in text:
            return text.split("T", 1)[0]
        if " " in text:
            return text.split(" ", 1)[0]
        return text[:10]

    import re
    text = re.sub(r"\s+(?=\d+[.)]\s+)", "\n", text)
    return text


def _make_display_rows(rows):
    return [{col: _display_value(row, col) for col in FINAL_COLUMNS} for row in rows]


def _make_batch_rows(rows):
    display = []
    for row in rows:
        created_at = str(row.get("created_at") or "")
        if "T" in created_at:
            created_at = created_at.replace("T", " ").split(".", 1)[0]
        display.append(
            {
                "Uploaded At": created_at,
                "Batch ID": row.get("batch_id", ""),
                "Status": row.get("status", ""),
                "Total Files": row.get("total_files", 0),
                "Completed": row.get("completed_files", 0),
                "Failed": row.get("failed_files", 0),
                "Report Sent": "Yes" if row.get("report_sent") else "No",
            }
        )
    return display


st.set_page_config(page_title="EduTap Call Scoring", page_icon="📞", layout="wide")
st.title("EduTap Call Scoring System")

tab1, tab2, tab3 = st.tabs(["Upload Calls", "View Results", "Backend Queue"])

if "call_uploader_key" not in st.session_state:
    st.session_state["call_uploader_key"] = 0

with tab1:
    st.subheader("Upload Call Recordings")
    st.caption("Upload MP3, WAV, or M4A files.")

    uploaded_files = st.file_uploader(
        "Choose call recording files",
        type=["mp3", "wav", "m4a"],
        accept_multiple_files=True,
        key=f"call_recordings_{st.session_state['call_uploader_key']}",
    )

    upload_result_message = st.session_state.get("upload_result_message")
    if uploaded_files and upload_result_message:
        del st.session_state["upload_result_message"]
        upload_result_message = None

    if not uploaded_files and upload_result_message:
        message_type = upload_result_message.get("type", "info")
        message_text = upload_result_message.get("text", "")
        result_overlay = st.empty()
        _render_result_overlay(result_overlay, message_text, message_type)

    if uploaded_files:
        st.info(f"{len(uploaded_files)} file(s) selected.")

        if st.button("Upload Calls", type="primary"):
            overlay = st.empty()
            error_items = []
            queued_files = []
            batch_id = None

            try:
                file_payloads = []
                total_files = len(uploaded_files)
                for index, uploaded_file in enumerate(uploaded_files, start=1):
                    _render_upload_overlay(overlay, index, total_files)
                    file_payloads.append(
                        {
                            "name": uploaded_file.name,
                            "bytes": uploaded_file.read(),
                            "student_number": extract_student_number(uploaded_file.name),
                        }
                    )

                batch_id, queued_files = enqueue_call_batch(file_payloads)
            except Exception as exc:
                simple_error = _simple_error_message(exc)
                error_items.append(
                    {
                        "filename": "Batch upload",
                        "student_number": "N/A",
                        "simple_error": simple_error,
                        "technical_error": str(exc),
                    }
                )
            finally:
                overlay.empty()

            if error_items:
                try:
                    send_error_report(error_items, batch_label=str(date.today()))
                except Exception:
                    pass
                st.session_state["upload_result_message"] = {
                    "type": "error",
                    "text": "The files could not be uploaded. Error details have been sent to the admin.",
                }
            else:
                workflow_started, workflow_message = _trigger_github_worker()
                success_message = f"{len(queued_files)} call(s) are uploaded successfully. You can close this window."

                if not workflow_started:
                    try:
                        send_error_report(
                            [
                                {
                                    "filename": "GitHub Actions auto-start",
                                    "student_number": "N/A",
                                    "simple_error": "Backend processing could not be started automatically.",
                                    "technical_error": workflow_message,
                                }
                            ],
                            batch_label=str(date.today()),
                        )
                    except Exception:
                        pass

                st.session_state["upload_result_message"] = {
                    "type": "success",
                    "text": success_message,
                }

                st.session_state["last_uploaded_batch"] = {
                    "batch_id": batch_id,
                    "files": queued_files,
                    "workflow_started": workflow_started,
                    "workflow_message": workflow_message,
                }

            st.session_state["call_uploader_key"] += 1
            st.rerun()

with tab2:
    st.subheader("Call Score Dashboard")

    if "dashboard_unlocked" not in st.session_state:
        st.session_state.dashboard_unlocked = False

    if not st.session_state.dashboard_unlocked:
        pwd = st.text_input("Enter password to view results", type="password")
        if st.button("Unlock"):
            if pwd == DASHBOARD_PASSWORD:
                st.session_state.dashboard_unlocked = True
                st.rerun()
            else:
                st.error("Wrong password.")
    else:
        col_a, col_b = st.columns([1, 5])
        with col_a:
            if st.button("Refresh"):
                st.rerun()

        try:
            rows = fetch_all_results()
        except Exception:
            st.error("Could not load results. Please contact the admin.")
            rows = []

        if not rows:
            st.info("No results yet.")
        else:
            full_analysis = [r for r in rows if r.get("Call Type") == "full_analysis"]
            follow_up_only = [r for r in rows if r.get("Call Type") == "follow_up_only"]
            not_worthy = [r for r in rows if r.get("Call Type") == "not_worthy"]
            converted = [r for r in rows if r.get("Converted Status") == "Converted"]

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Total Calls", len(rows))
            c2.metric("Full Analysis", len(full_analysis))
            c3.metric("Follow-up Only", len(follow_up_only))
            c4.metric("Not Worthy", len(not_worthy))
            c5.metric("Converted", len(converted))

            df = pd.DataFrame(_make_display_rows(rows), columns=FINAL_COLUMNS)

            column_config = {}
            try:
                column_config = {
                    "Call Recording Link": st.column_config.LinkColumn("Call Recording Link", width="medium"),
                    "Transcript Link": st.column_config.LinkColumn("Transcript Link", width="medium"),
                    "Average Score": st.column_config.TextColumn("Average Score", width="small"),
                    "Score Parameter Wise": st.column_config.TextColumn("Score Parameter Wise", width="medium"),
                    "Strengths": st.column_config.TextColumn("Strengths", width="large"),
                    "Improvement Areas": st.column_config.TextColumn("Improvement Areas", width="large"),
                    "Learnings": st.column_config.TextColumn("Learnings", width="large"),
                }
            except Exception:
                column_config = {}

            st.dataframe(df, use_container_width=True, height=650, column_config=column_config)

with tab3:
    st.subheader("Backend Queue")
    st.caption("This shows recent upload batches waiting for or completed by the GitHub backend worker.")

    if "queue_unlocked" not in st.session_state:
        st.session_state.queue_unlocked = False

    if not st.session_state.queue_unlocked:
        queue_pwd = st.text_input("Enter password to view backend queue", type="password", key="queue_pwd")
        if st.button("Unlock Queue"):
            if queue_pwd == DASHBOARD_PASSWORD:
                st.session_state.queue_unlocked = True
                st.rerun()
            else:
                st.error("Wrong password.")
    else:
        if st.button("Refresh Queue"):
            st.rerun()

        last_batch = st.session_state.get("last_uploaded_batch")
        if last_batch:
            safe_batch_id = html.escape(str(last_batch.get("batch_id", "")))
            st.info(f"Last uploaded batch: {safe_batch_id}")

        try:
            batch_rows = fetch_recent_batches(limit=50)
        except Exception:
            st.error("Could not load backend queue. Please contact the admin.")
            batch_rows = []

        if not batch_rows:
            st.info("No backend batches yet.")
        else:
            batch_df = pd.DataFrame(_make_batch_rows(batch_rows))
            st.dataframe(batch_df, use_container_width=True, height=520)

        st.markdown("### What happens next?")
        st.write(
            "After upload, GitHub Actions processes pending calls in the backend. "
            "When a batch finishes, the email report is sent automatically."
        )
