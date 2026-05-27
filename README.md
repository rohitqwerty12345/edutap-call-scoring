# EduTap Call Scoring System

This version uses backend processing through GitHub Actions.

## Flow

1. Support uploads call recordings in Streamlit.
2. Streamlit uploads the files to Supabase Storage and creates pending jobs.
3. Support can close the browser after upload success.
4. Streamlit automatically triggers the GitHub Actions backend worker immediately after a successful upload.
5. Worker processes pending jobs through Deepgram + OpenAI.
6. Results are saved in Supabase and the XLSX report is emailed.
7. Failed calls are emailed to `ERROR_RECIPIENT_EMAILS`.

## Files to replace/add

Replace:

```text
app.py
pipeline.py
supabase_client.py
supabase_migration.sql
README.md
.env.example
```

Add:

```text
worker.py
.github/workflows/process-calls.yml
```

Other files can stay as they are.

## Supabase

Run the latest `supabase_migration.sql` in Supabase SQL Editor.

It creates:

```text
call_scores
call_processing_batches
call_processing_jobs
call-recordings bucket
call-transcripts bucket
```


## Streamlit secrets for auto-starting GitHub Actions

Add these extra secrets in Streamlit Cloud → App → Settings → Secrets. These are needed because Streamlit is the app that starts the GitHub backend worker after upload.

```toml
GITHUB_ACTIONS_TOKEN = "your_github_fine_grained_token_here"
GITHUB_REPO_OWNER = "rohitqwerty12345"
GITHUB_REPO_NAME = "edutap-call-scoring"
GITHUB_WORKFLOW_FILE = "process-calls.yml"
GITHUB_WORKFLOW_REF = "main"
```

The GitHub token should be a fine-grained personal access token with access to this repository and permission to run Actions workflows. Keep this token only in Streamlit Secrets, never inside GitHub files.

## GitHub Actions secrets

Add these in GitHub repo → Settings → Secrets and variables → Actions → Repository secrets:

```text
DEEPGRAM_API_KEY
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_REASONING_EFFORT
SUPABASE_URL
SUPABASE_KEY
SENDER_EMAIL
SENDER_PASSWORD
RECIPIENT_EMAILS
ERROR_RECIPIENT_EMAILS
MAX_PARALLEL_CALLS
MAX_JOBS_PER_RUN
```

Recommended values:

```text
OPENAI_MODEL = gpt-5.5
OPENAI_REASONING_EFFORT = medium
MAX_PARALLEL_CALLS = 5
MAX_JOBS_PER_RUN = 50
```

## Running the backend worker

Immediate automatic run:

```text
Upload in Streamlit → pending jobs created → GitHub Actions starts automatically
```

Fallback scheduled run:

```text
Daily at 8 PM IST
```

Manual run if needed:

```text
GitHub repo → Actions → Process Pending EduTap Calls → Run workflow
```

## GitHub Actions safety

The workflow has:

```text
timeout-minutes: 65
```

So one run cannot continue forever.
