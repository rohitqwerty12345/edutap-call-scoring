import json
import os
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from email_sender import send_report
from pipeline import process_single_file
from supabase_client import fetch_all_results

load_dotenv()


def get_setting(name: str, default: str | None = None) -> str | None:
    """Read from environment first, then Streamlit secrets if available."""
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

st.set_page_config(
    page_title="EduTap Call Scoring",
    page_icon="📞",
    layout="wide",
)

st.title("EduTap EPFO Call Scoring System")

tab1, tab2, tab3 = st.tabs(["Upload Calls", "View Results", "Debug Last Run"])

# -------------------------------------------------
# TAB 1: UPLOAD
# -------------------------------------------------
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
            results_this_batch = []
            saved_rows_this_batch = []
            debug_items_this_batch = []

            progress_bar = st.progress(0)
            status_area = st.empty()

            for idx, uploaded_file in enumerate(uploaded_files):
                status_area.info(
                    f"Processing {idx + 1}/{len(uploaded_files)}: {uploaded_file.name}"
                )

                try:
                    file_bytes = uploaded_file.read()
                    result = process_single_file(file_bytes, uploaded_file.name)

                    results_this_batch.append(result)
                    saved_rows_this_batch.append(result["saved_row"])
                    debug_items_this_batch.append(
                        {
                            "filename": result["filename"],
                            "student_number": result["student_number"],
                            "worthy": result["worthy"],
                            **result["debug"],
                        }
                    )

                    if result["worthy"]:
                        status_area.success(f"Scored successfully: {uploaded_file.name}")
                    else:
                        status_area.warning(
                            f"Not analysis worthy, saved with tag: {uploaded_file.name}"
                        )

                except Exception as exc:
                    status_area.error(f"Error in {uploaded_file.name}: {exc}")
                    debug_items_this_batch.append(
                        {
                            "filename": uploaded_file.name,
                            "error": str(exc),
                        }
                    )

                progress_bar.progress((idx + 1) / len(uploaded_files))

            st.session_state["last_run_debug"] = debug_items_this_batch

            if saved_rows_this_batch:
                try:
                    today_label = str(date.today())
                    send_report(saved_rows_this_batch, batch_label=today_label)
                    st.success(
                        f"Finished. {len(saved_rows_this_batch)} file(s) saved and email report sent."
                    )
                except Exception as exc:
                    st.warning(
                        f"Files were processed and saved, but email sending failed: {exc}"
                    )
            else:
                st.error("No files were successfully processed.")

            st.success("Upload complete.")
            st.info("Temporary debug data is available in the Debug Last Run tab.")

# -------------------------------------------------
# TAB 2: DASHBOARD
# -------------------------------------------------
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
        except Exception as exc:
            st.error(f"Could not load results: {exc}")
            rows = []

        if not rows:
            st.info("No results yet.")
        else:
            display_rows = []
            for r in rows:
                if not r.get("analysis_worthy"):
                    display_rows.append(
                        {
                            "Date": str(r.get("created_at", ""))[:10],
                            "Student Number": r.get("student_number", ""),
                            "Worthy": "Not Worthy",
                            "Guardrails": "—",
                            "Opening": "—",
                            "Discovery": "—",
                            "Evidence": "—",
                            "Resonance": "—",
                            "Diagnosis": "—",
                            "Closure": "—",
                            "Overall": "—",
                        }
                    )
                else:
                    display_rows.append(
                        {
                            "Date": str(r.get("created_at", ""))[:10],
                            "Student Number": r.get("student_number", ""),
                            "Worthy": "Yes",
                            "Guardrails": r.get("guardrails", ""),
                            "Opening": r.get("opening_score", ""),
                            "Discovery": r.get("discovery_score", ""),
                            "Evidence": r.get("evidence_score", ""),
                            "Resonance": r.get("resonance_score", ""),
                            "Diagnosis": r.get("diagnosis_score", ""),
                            "Closure": r.get("closure_score", ""),
                            "Overall": r.get("overall_score", ""),
                        }
                    )

            df = pd.DataFrame(display_rows)

            def highlight_guardrails(val):
                if val == "PASS":
                    return "background-color: #EAF3DE; color: #27500A"
                if val == "FAIL":
                    return "background-color: #FCEBEB; color: #791F1F"
                return ""

            try:
                styled = df.style.map(highlight_guardrails, subset=["Guardrails"])
            except AttributeError:
                styled = df.style.applymap(highlight_guardrails, subset=["Guardrails"])

            st.dataframe(styled, use_container_width=True, height=500)

            st.divider()
            st.subheader("Detailed Coaching Notes")

            for r in rows:
                if r.get("analysis_worthy"):
                    title = (
                        f"Student {r.get('student_number', 'unknown')} - "
                        f"{str(r.get('created_at', ''))[:10]}"
                    )
                    with st.expander(title):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("**Top Strength**")
                            st.write(r.get("top_strength", ""))
                        with col2:
                            st.markdown("**Biggest Improvement Area**")
                            st.write(r.get("biggest_improvement_area", ""))

                        st.markdown("**Coaching Note**")
                        st.write(r.get("coaching_note", ""))

                        with st.expander("Transcript"):
                            st.text(r.get("call_transcript", ""))

# -------------------------------------------------
# TAB 3: TEMPORARY DEBUG
# -------------------------------------------------
with tab3:
    st.subheader("Debug Last Run")
    st.warning(
        "Temporary testing tab. It shows Deepgram transcript, OpenAI prompt, and OpenAI output for the latest run in this browser session. Remove before final support-team release."
    )

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
                        continue

                    st.markdown("### File information")
                    st.write(
                        {
                            "filename": item.get("filename"),
                            "student_number": item.get("student_number"),
                            "worthy": item.get("worthy"),
                            "openai_model": item.get("openai_model"),
                            "openai_reasoning_effort": item.get("openai_reasoning_effort"),
                        }
                    )

                    st.markdown("### 1. Deepgram transcript output")
                    st.text_area(
                        "Deepgram transcript",
                        value=item.get("deepgram_transcript", ""),
                        height=300,
                        key=f"deepgram_{title}",
                    )

                    st.markdown("### 2. Prompt sent to OpenAI GPT")
                    st.text_area(
                        "System prompt / instructions",
                        value=item.get("openai_system_prompt", ""),
                        height=350,
                        key=f"prompt_{title}",
                    )

                    st.text_area(
                        "User input sent to OpenAI",
                        value=item.get("openai_user_input", ""),
                        height=250,
                        key=f"user_input_{title}",
                    )

                    st.markdown("### 3. Raw OpenAI output")
                    st.text_area(
                        "Raw OpenAI output",
                        value=item.get("openai_raw_output", ""),
                        height=300,
                        key=f"raw_output_{title}",
                    )

                    st.markdown("### 4. Parsed output used by code")
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
