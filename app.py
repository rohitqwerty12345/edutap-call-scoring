import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from email_sender import send_report
from pipeline import process_single_file
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


st.set_page_config(page_title="EduTap Call Scoring", page_icon="📞", layout="wide")
st.title("EduTap EPFO Call Scoring System")

tab1, tab2, tab3 = st.tabs(["Upload Calls", "View Results", "Debug Last Run"])


def _display_value(row, key, default=""):
    value = row.get(key, default)
    if value is None:
        return default
    text = str(value)
    # Make numbered point paragraphs easier to read in expanded cell view/tooltips.
    import re
    text = re.sub(r"\s+(?=\d+[.)]\s+)", "\n", text.strip())
    return text


def _make_display_rows(rows):
    display_rows = []
    for row in rows:
        display_rows.append({col: _display_value(row, col) for col in FINAL_COLUMNS})
    return display_rows


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

            file_payloads = [{"name": f.name, "bytes": f.read()} for f in uploaded_files]
            max_workers = get_max_parallel_calls(len(file_payloads))
            status_area.info(f"Processing {len(file_payloads)} file(s) with {max_workers} parallel worker(s).")

            completed_count = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {
                    executor.submit(process_single_file, payload["bytes"], payload["name"]): payload["name"]
                    for payload in file_payloads
                }

                for future in as_completed(future_to_file):
                    filename = future_to_file[future]
                    try:
                        result = future.result()
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
                        status_area.success(f"Processed successfully: {filename}")
                    except Exception as exc:
                        status_area.error(f"Error in {filename}: {exc}")
                        debug_items_this_batch.append({"filename": filename, "error": str(exc)})

                    completed_count += 1
                    progress_bar.progress(completed_count / len(file_payloads))

            st.session_state["last_run_debug"] = debug_items_this_batch

            if saved_rows_this_batch:
                try:
                    today_label = str(date.today())
                    send_report(saved_rows_this_batch, batch_label=today_label)
                    st.success(f"Finished. {len(saved_rows_this_batch)} file(s) saved and email report sent.")
                except Exception as exc:
                    st.warning(f"Files were processed and saved, but email sending failed: {exc}")
            else:
                st.error("No files were successfully processed.")

            st.success("Upload complete.")
            st.info("Temporary debug data is available in the Debug Last Run tab.")


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
