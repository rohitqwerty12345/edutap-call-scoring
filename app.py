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


def _display_value(row, key, default=""):
    value = row.get(key, default)
    return default if value is None else value


def _score_parameter_wise(row):
    if not row.get("analysis_worthy"):
        return "Not Analysis Worthy"

    parts = [
        f"Guardrails: {row.get('guardrails', '')}",
        f"Opening: {row.get('opening_score', '')}/10" if row.get("opening_score") else "Opening: ",
        f"Discovery: {row.get('discovery_score', '')}/10" if row.get("discovery_score") else "Discovery: ",
        f"Evidence: {row.get('evidence_score', '')}/10" if row.get("evidence_score") else "Evidence: ",
        f"Resonance: {row.get('resonance_score', '')}/10" if row.get("resonance_score") else "Resonance: ",
        f"Diagnosis: {row.get('diagnosis_score', '')}",
        f"Closure: {row.get('closure_score', '')}/10" if row.get("closure_score") else "Closure: ",
    ]
    return "\n".join(parts)


def _make_display_rows(rows):
    display_rows = []

    for r in rows:
        base_cols = {
            "Date": str(r.get("created_at", ""))[:10],
            "Student Number": _display_value(r, "student_number"),
            "Call Recording Link": _display_value(r, "call_audio_link"),
            "Converted Status": _display_value(r, "converted_status", "Not converted"),
            "Overall Score": _display_value(r, "overall_score"),
            "Score Parameter Wise": _score_parameter_wise(r),
            "Top Strength": _display_value(r, "top_strength", "—"),
            "Biggest Improvement Area": _display_value(r, "biggest_improvement_area", "—"),
            "Coaching Note": _display_value(r, "coaching_note", "—"),
        }

        if not r.get("analysis_worthy"):
            base_cols.update(
                {
                    "Transcript Link": _display_value(r, "call_transcript_link"),
                    "Worthy": "Not Worthy",
                    "Guardrails": "—",
                    "Guardrails Reason": "—",
                    "Opening Score": "—",
                    "Opening Quote": "—",
                    "Discovery Score": "—",
                    "Discovery Questions": "—",
                    "Discovery Found Out": "—",
                    "Evidence Score": "—",
                    "Evidence Detail": "—",
                    "Resonance Score": "—",
                    "Resonance Detail": "—",
                    "Diagnosis Score": "—",
                    "Diagnosis Detail": "—",
                    "Closure Score": "—",
                    "Closure Detail": "—",
                }
            )
        else:
            base_cols.update(
                {
                    "Transcript Link": _display_value(r, "call_transcript_link"),
                    "Worthy": "Yes",
                    "Guardrails": _display_value(r, "guardrails"),
                    "Guardrails Reason": _display_value(r, "guardrails_reason"),
                    "Opening Score": _display_value(r, "opening_score"),
                    "Opening Quote": _display_value(r, "opening_quote"),
                    "Discovery Score": _display_value(r, "discovery_score"),
                    "Discovery Questions": _display_value(r, "discovery_questions_asked_by_agent"),
                    "Discovery Found Out": _display_value(r, "discovery_what_agent_found_out"),
                    "Evidence Score": _display_value(r, "evidence_score"),
                    "Evidence Detail": _display_value(r, "evidence_why_this_score"),
                    "Resonance Score": _display_value(r, "resonance_score"),
                    "Resonance Detail": _display_value(r, "resonance_why_this_score"),
                    "Diagnosis Score": _display_value(r, "diagnosis_score"),
                    "Diagnosis Detail": _display_value(r, "diagnosis_why_this_score"),
                    "Closure Score": _display_value(r, "closure_score"),
                    "Closure Detail": _display_value(r, "closure_why_this_score"),
                }
            )

        display_rows.append(base_cols)

    return display_rows

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
            worthy_rows = [r for r in rows if r.get("analysis_worthy")]
            converted_count = sum(1 for r in worthy_rows if r.get("converted_status") == "Converted")
            not_converted_count = len(worthy_rows) - converted_count

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Calls", len(rows))
            col2.metric("Analysis Worthy", len(worthy_rows))
            col3.metric("Converted", converted_count)
            col4.metric("Not Converted", not_converted_count)

            df = pd.DataFrame(_make_display_rows(rows))

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

            column_config = {}
            try:
                column_config = {
                    "Call Recording Link": st.column_config.LinkColumn("Call Recording Link"),
                    "Transcript Link": st.column_config.LinkColumn("Transcript Link"),
                }
            except Exception:
                column_config = {}

            st.dataframe(
                styled,
                use_container_width=True,
                height=550,
                column_config=column_config,
            )

            st.divider()
            st.subheader("Detailed GPT Output")

            for r in rows:
                title = (
                    f"Student {r.get('student_number', 'unknown')} - "
                    f"{str(r.get('created_at', ''))[:10]} - "
                    f"{r.get('converted_status', 'Not converted')}"
                )

                with st.expander(title):
                    st.markdown("**Links**")
                    st.write(f"Call recording: {r.get('call_audio_link', '')}")
                    st.write(f"Transcript link: {r.get('call_transcript_link', '')}")

                    if not r.get("analysis_worthy"):
                        st.warning("Not analysis worthy")
                        with st.expander("Transcript"):
                            st.text(r.get("call_transcript", ""))
                        continue

                    st.markdown("### Guardrails")
                    st.write(
                        {
                            "result": r.get("guardrails"),
                            "reason": r.get("guardrails_reason"),
                            "false_information_flagged": r.get("guardrails_false_information_flagged"),
                            "false_information_detail": r.get("guardrails_false_information_detail"),
                        }
                    )

                    st.markdown("### Opening")
                    st.write(
                        {
                            "score": r.get("opening_score"),
                            "what_agent_said_right_after_intro": r.get("opening_what_agent_said_right_after_intro"),
                            "quote": r.get("opening_quote"),
                            "specific_to_student_trial_activity": r.get("opening_specific_to_student_trial_activity"),
                            "why_this_score": r.get("opening_why_this_score"),
                        }
                    )

                    st.markdown("### Discovery")
                    st.write(
                        {
                            "score": r.get("discovery_score"),
                            "questions_asked_by_agent": r.get("discovery_questions_asked_by_agent"),
                            "what_agent_found_out": r.get("discovery_what_agent_found_out"),
                            "student_said_own_problem_out_loud": r.get("discovery_student_said_own_problem_out_loud"),
                            "best_discovery_moment_quote": r.get("discovery_best_discovery_moment_quote"),
                            "why_this_score": r.get("discovery_why_this_score"),
                        }
                    )

                    st.markdown("### Evidence")
                    st.write(
                        {
                            "score": r.get("evidence_score"),
                            "discovery_finding_used": r.get("evidence_discovery_finding_used"),
                            "master_course_feature_connected": r.get("evidence_master_course_feature_connected"),
                            "factually_accurate_about_master_course": r.get("evidence_factually_accurate_about_master_course"),
                            "inaccuracy_detail": r.get("evidence_inaccuracy_detail"),
                            "quote": r.get("evidence_quote"),
                            "why_this_score": r.get("evidence_why_this_score"),
                        }
                    )

                    st.markdown("### Resonance")
                    st.write(
                        {
                            "score": r.get("resonance_score"),
                            "source_of_urgency": r.get("resonance_source_of_urgency"),
                            "student_situation_used": r.get("resonance_student_situation_used"),
                            "quote": r.get("resonance_quote"),
                            "why_this_score": r.get("resonance_why_this_score"),
                        }
                    )

                    st.markdown("### Diagnosis")
                    st.write(
                        {
                            "score": r.get("diagnosis_score"),
                            "na": r.get("diagnosis_na"),
                            "objection_raised_by_student": r.get("diagnosis_objection_raised_by_student"),
                            "surface_reason_stated": r.get("diagnosis_surface_reason_stated"),
                            "real_reason_found": r.get("diagnosis_real_reason_found"),
                            "quote_of_diagnosis_attempt": r.get("diagnosis_quote_of_diagnosis_attempt"),
                            "why_this_score": r.get("diagnosis_why_this_score"),
                        }
                    )

                    st.markdown("### Closure")
                    st.write(
                        {
                            "score": r.get("closure_score"),
                            "what_happened_at_end": r.get("closure_what_happened_at_end"),
                            "payment_link_sent": r.get("closure_payment_link_sent"),
                            "followup_date_and_time_agreed": r.get("closure_followup_date_and_time_agreed"),
                            "course_details_sent_on_whatsapp": r.get("closure_course_details_sent_on_whatsapp"),
                            "quote_of_closing_line": r.get("closure_quote_of_closing_line"),
                            "why_this_score": r.get("closure_why_this_score"),
                        }
                    )

                    st.markdown("### Overall / Coaching")
                    st.write(
                        {
                            "overall_score": r.get("overall_score"),
                            "top_strength": r.get("top_strength"),
                            "biggest_improvement_area": r.get("biggest_improvement_area"),
                            "coaching_note": r.get("coaching_note"),
                        }
                    )

                    with st.expander("Transcript"):
                        st.text(r.get("call_transcript", ""))

                    with st.expander("Raw AI JSON from database"):
                        st.json(r.get("ai_output_json", {}))

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
