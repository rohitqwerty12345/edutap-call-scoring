# EduTap Call Scoring System

This version supports both normal OpenAI processing and optional OpenAI Batch API processing.

## Main flow

1. Student partners upload call recordings in Streamlit.
2. Streamlit saves audio files in Supabase Storage and creates pending jobs.
3. Streamlit automatically triggers GitHub Actions.
4. GitHub Actions worker processes the jobs.
5. Results are saved in Supabase.
6. Email is sent with:
   - a quick formatted table in the email body: Recording, Score, Parameter Score
   - the full XLSX report attached

## Processing modes

Set this secret in GitHub Actions:

```text
OPENAI_PROCESSING_MODE=standard
```

or:

```text
OPENAI_PROCESSING_MODE=batch
```

### Standard mode

```text
Audio -> Deepgram transcript -> OpenAI immediate scoring -> Supabase -> Email
```

Use this when you want faster results.

### Batch mode

```text
Audio -> Deepgram transcript -> OpenAI Batch API submission -> scheduled polling -> Supabase -> Email
```

Use this when lower OpenAI cost is more important than instant results.

Batch mode does not keep GitHub Actions running for 24 hours. The worker submits the OpenAI batch and exits. The scheduled workflow checks every 30 minutes and completes the results when OpenAI output is ready.

## Files included

Replace/add these files in GitHub:

```text
app.py
deepgram_client.py
email_sender.py
openai_client.py
pipeline.py
scoring_prompt.py
supabase_client.py
supabase_migration.sql
worker.py
requirements.txt
README.md
.env.example
env.example
.github/workflows/process-calls.yml
```

## Supabase

Run `supabase_migration.sql` once in Supabase SQL Editor after replacing files.

It ensures:

```text
call_scores
call_processing_batches
call_processing_jobs
student_call_counters
call-recordings bucket
call-transcripts bucket
```

It also adds internal Batch API columns such as:

```text
processing_mode
openai_batch_id
openai_input_file_id
openai_output_file_id
openai_batch_status
transcript_text
openai_custom_id
openai_response_json
```

## Streamlit Secrets

Streamlit needs secrets for upload, Supabase, and GitHub auto-trigger.

```toml
DEEPGRAM_API_KEY = "..."
OPENAI_API_KEY = "..."
OPENAI_MODEL = "gpt-5.5"
OPENAI_REASONING_EFFORT = "medium"
OPENAI_PROCESSING_MODE = "standard"
SUPABASE_URL = "..."
SUPABASE_KEY = "..."
SENDER_EMAIL = "..."
SENDER_PASSWORD = "..."
RECIPIENT_EMAILS = "..."
ERROR_RECIPIENT_EMAILS = "..."
DASHBOARD_PASSWORD = "show123"
MAX_PARALLEL_CALLS = "5"
MAX_JOBS_PER_RUN = "50"
GITHUB_ACTIONS_TOKEN = "..."
GITHUB_REPO_OWNER = "rohitqwerty12345"
GITHUB_REPO_NAME = "edutap-call-scoring"
GITHUB_WORKFLOW_FILE = "process-calls.yml"
GITHUB_WORKFLOW_REF = "main"
```

## GitHub Actions Secrets

Add these in GitHub repo -> Settings -> Secrets and variables -> Actions:

```text
DEEPGRAM_API_KEY
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_REASONING_EFFORT
OPENAI_PROCESSING_MODE
SUPABASE_URL
SUPABASE_KEY
SENDER_EMAIL
SENDER_PASSWORD
RECIPIENT_EMAILS
ERROR_RECIPIENT_EMAILS
MAX_PARALLEL_CALLS
MAX_JOBS_PER_RUN
```

Recommended:

```text
OPENAI_MODEL = gpt-5.5
OPENAI_REASONING_EFFORT = medium
OPENAI_PROCESSING_MODE = standard
MAX_PARALLEL_CALLS = 5
MAX_JOBS_PER_RUN = 50
```

To enable OpenAI Batch API:

```text
OPENAI_PROCESSING_MODE = batch
```

## GitHub workflow

The workflow runs:

```text
1. Automatically after Streamlit upload
2. Every 30 minutes by schedule
3. Manually from GitHub Actions if needed
```

The 30-minute schedule is mainly for Batch API polling. In standard mode, it exits quickly if no pending jobs are found.

## What stays unchanged

The dashboard and XLSX email report still show only the final visible columns.

Internal fields remain hidden:

```text
call_number
call_summary_for_followup
openai_batch_id
transcript_text
openai_response_json
```

## Testing order

1. Replace files in GitHub.
2. Run `supabase_migration.sql`.
3. Add/update GitHub secret `OPENAI_PROCESSING_MODE`.
4. Start with `OPENAI_PROCESSING_MODE=standard`.
5. Upload 1 call and confirm result/email.
6. Switch to `OPENAI_PROCESSING_MODE=batch`.
7. Upload 1 call and wait for the scheduled poller to complete.
8. Then test 5 calls, then full daily batch.
