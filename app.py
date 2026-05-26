import html
import json
import os
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from email_sender import send_error_report, send_report
from pipeline import extract_student_number, process_single_file
from supabase_client import fetch_all_results

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


def get_max_parallel_calls(total_files: int) -> int:
    raw_value = get_setting("MAX_PARALLEL_CALLS", "5")
    try:
        workers = int(raw_value or "5")
    except ValueError:
        workers = 5
    workers = max(1, workers)
    workers = min(workers, total_files)
    workers = min(workers, 20)
    return workers


def _simple_error_message(exc: Exception) -> str:
    text = str(exc or "").lower()

    if "deepgram_api_key" in text:
        return "The transcription service is not set up. Please contact the admin."
    if "openai_api_key" in text:
        return "The scoring service is not set up. Please contact the admin."
    if "supabase_url" in text or "supabase_key" in text:
        return "The database connection is not set up. Please contact the admin."
    if "sender_email" in text or "sender_password" in text or "recipient_emails" in text:
        return "The email report could not be sent. Please contact the admin."
    if "no transcript words returned" in text:
        return "We could not read the audio clearly. Please check the recording and try again."
    if "json" in text or "expecting value" in text or "decode" in text:
        return "The scoring result could not be read properly. Please try this file again."
    if "timeout" in text or "timed out" in text:
        return "Processing took too long. Please try again with a smaller batch."
    if "storage" in text or "bucket" in text or "upload" in text:
        return "The call file could not be saved. Please contact the admin."
    if "database" in text or "relation" in text or "column" in text or "insert" in text:
        return "The result could not be saved. Please contact the admin."

    return "This call could not be processed. Please try again or contact the admin."


def _render_processing_overlay(placeholder, current: int, total: int) -> None:
    current = max(1, min(current, total))
    percent = (current / total) * 100
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
        .edutap-processing-dots span {{
            display: inline-block;
            width: 6px;
            height: 6px;
            margin: 0 3px;
            border-radius: 50%;
            background: #ef4444;
            animation: edutap-dot 1.2s ease-in-out infinite;
        }}
        .edutap-processing-dots span:nth-child(2) {{ animation-delay: 0.15s; }}
        .edutap-processing-dots span:nth-child(3) {{ animation-delay: 0.30s; }}
        @keyframes edutap-dot {{
            0%, 80%, 100% {{ opacity: 0.25; transform: translateY(0); }}
            40% {{ opacity: 1; transform: translateY(-5px); }}
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
                <div class="edutap-processing-title">Processing calls</div>
                <div class="edutap-processing-subtitle">Processing {current} of {total} <span class="edutap-processing-dots"><span></span><span></span><span></span></span></div>
                <div class="edutap-processing-bar"><div class="edutap-processing-fill"></div></div>
                <div class="edutap-processing-note">Please keep this window open until processing is complete.</div>
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

    # The Date column should show only YYYY-MM-DD, not timestamp/timezone.
    if key == "Date":
        if "T" in text:
            return text.split("T", 1)[0]
        if " " in text:
            return text.split(" ", 1)[0]
        return text[:10]

    # Make numbered point paragraphs easier to read in expanded cell view/tooltips.
    import re
    text = re.sub(r"\s+(?=\d+[.)]\s+)", "\n", text)
    return text


def _make_display_rows(rows):
    display_rows = []
    for row in rows:
        display_rows.append({col: _display_value(row, col) for col in FINAL_COLUMNS})
    return display_rows


st.set_page_config(page_title="EduTap Call Scoring", page_icon="📞", layout="wide")
st.title("EduTap Call Scoring System")

tab1, tab2, tab3 = st.tabs(["Upload Calls", "View Results", "Debug Last Run"])

with tab1:
    st.subheader("Upload Call Recordings")
    st.caption("Upload MP3, WAV, or M4A files. Processing begins after you click Analyze.")

    uploaded_files = st.file_uploader(
        "Choose call recording files",
        type=["mp3", "wav", "m4a"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        st.info(f"{len(uploaded_files)} file(s) selected.")

        if st.button("Analyze All Calls", type="primary"):
            saved_rows_this_batch = []
            debug_items_this_batch = []
            error_items_this_batch = []
            overlay = st.empty()

            file_payloads = [{"name": f.name, "bytes": f.read()} for f in uploaded_files]
            total_files = len(file_payloads)
            today_label = str(date.today())

            for index, payload in enumerate(file_payloads, start=1):
                filename = payload["name"]
                student_number = extract_student_number(filename)
                _render_processing_overlay(overlay, index, total_files)

                try:
                    result = process_single_file(payload["bytes"], filename)
                    saved_rows_this_batch.append(result["saved_row"])
                    debug_items_this_batch.append(
                        {
                            "filename": result["filename"],
                            "student_number": result["student_number"],
                            "call_type": result.get("call_type"),
                            "worthy": result["worthy"],
                            **result["debug"],
                        }
                    )
                except Exception as exc:
                    simple_error = _simple_error_message(exc)
                    technical_error = str(exc)
                    error_items_this_batch.append(
                        {
                            "filename": filename,
                            "student_number": student_number,
                            "simple_error": simple_error,
                            "technical_error": technical_error,
                        }
                    )
                    debug_items_this_batch.append(
                        {
                            "filename": filename,
                            "student_number": student_number,
                            "error": simple_error,
                            "technical_error": technical_error,
                        }
                    )

            st.session_state["last_run_debug"] = debug_items_this_batch
            overlay.empty()

            report_error_items = []
            if saved_rows_this_batch:
                try:
                    send_report(saved_rows_this_batch, batch_label=today_label)
                except Exception as exc:
                    report_error_items.append(
                        {
                            "filename": "Daily email report",
                            "student_number": "N/A",
                            "simple_error": _simple_error_message(exc),
                            "technical_error": str(exc),
                        }
                    )

            all_error_items = error_items_this_batch + report_error_items
            error_email_sent = False
            if all_error_items:
                try:
                    send_error_report(all_error_items, batch_label=today_label)
                    error_email_sent = True
                except Exception:
                    error_email_sent = False

            if not all_error_items and saved_rows_this_batch:
                st.success("All calls processed successfully. You can now close this window.")
            elif saved_rows_this_batch and all_error_items:
                if error_email_sent:
                    st.warning("Some calls could not be processed. Successful calls are saved. Error details have been sent by email. You can now close this window.")
                else:
                    st.warning("Some calls could not be processed. Successful calls are saved. Please contact the admin. You can now close this window.")
            else:
                if error_email_sent:
                    st.error("We could not process the uploaded calls. Error details have been sent by email. Please try again or contact the admin.")
                else:
                    st.error("We could not process the uploaded calls. Please try again or contact the admin.")

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
    st.subheader("Debug Last Run")
    st.warning("Temporary testing tab. Remove before final support-team release.")

    if "debug_unlocked" not in st.session_state:
        st.session_state.debug_unlocked = False

    if not st.session_state.debug_unlocked:
        debug_pwd = st.text_input("Enter password to view debug data", type="password", key="debug_pwd")
        if st.button("Unlock Debug"):
            if debug_pwd == DASHBOARD_PASSWORD:
                st.session_state.debug_unlocked = True
                st.rerun()
            else:
                st.error("Wrong password.")
    else:
        debug_items = st.session_state.get("last_run_debug", [])
        if not debug_items:
            st.info("No debug data yet. Upload and analyze one call first.")
        else:
            for item in debug_items:
                title = item.get("filename", "unknown file")
                with st.expander(title, expanded=True):
                    if item.get("error"):
                        st.error(item["error"])
                        if item.get("technical_error"):
                            st.caption("Technical detail is hidden from normal users but available here for debugging.")
                            st.code(str(item["technical_error"]))
                        continue

                    st.markdown("### File information")
                    st.write(
                        {
                            "filename": item.get("filename"),
                            "student_number": item.get("student_number"),
                            "call_type": item.get("call_type"),
                            "worthy": item.get("worthy"),
                            "openai_model": item.get("openai_model"),
                            "openai_reasoning_effort": item.get("openai_reasoning_effort"),
                        }
                    )

                    st.markdown("### Deepgram transcript output")
                    st.text_area("Deepgram transcript", value=item.get("deepgram_transcript", ""), height=300, key=f"deepgram_{title}")

                    st.markdown("### Prompt sent to OpenAI GPT")
                    st.text_area("System prompt / instructions", value=item.get("openai_system_prompt", ""), height=350, key=f"prompt_{title}")
                    st.text_area("User input sent to OpenAI", value=item.get("openai_user_input", ""), height=250, key=f"user_input_{title}")

                    st.markdown("### Raw OpenAI output")
                    st.text_area("Raw OpenAI output", value=item.get("openai_raw_output", ""), height=300, key=f"raw_output_{title}")

                    st.markdown("### Parsed output used by code")
                    parsed = item.get("openai_parsed_output")
                    if isinstance(parsed, (dict, list)):
                        st.json(parsed)
                    else:
                        st.code(str(parsed))

                    debug_download = json.dumps(item, ensure_ascii=False, indent=2, default=str)
                    st.download_button(
                        "Download debug JSON",
                        data=debug_download,
                        file_name=f"debug_{item.get('student_number', 'unknown')}.json",
                        mime="application/json",
                        key=f"download_{title}",
                    )
