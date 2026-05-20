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

tab1, tab2 = st.tabs(["Upload Calls", "View Results"])

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

                    if result["worthy"]:
                        status_area.success(f"Scored successfully: {uploaded_file.name}")
                    else:
                        status_area.warning(
                            f"Not analysis worthy, saved with tag: {uploaded_file.name}"
                        )

                except Exception as exc:
                    status_area.error(f"Error in {uploaded_file.name}: {exc}")

                progress_bar.progress((idx + 1) / len(uploaded_files))

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
