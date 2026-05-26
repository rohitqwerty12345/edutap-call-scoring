# EduTap EPFO Call Scoring System

Final simplified version.

## Final scoring parameters

Visible names used in prompt, dashboard rows, Supabase text, and email report:

1. Tone + Truth
2. Opening
3. Pain Point Discovery
4. Evidence
5. Personal Urgency
6. Hesitation Discovery
7. Next Step Clarity


## Final database/dashboard columns

The `call_scores` table should have only these columns:

1. Date (date only, YYYY-MM-DD)
2. Student Number
3. Call Type
4. Call Recording Link
5. Converted Status
6. Average Score
7. Score Parameter Wise
8. Strengths
9. Improvement Areas
10. Learnings
11. Transcript Link

## Email report columns

The XLSX sent on email has only these columns:

1. Call Recording Link
2. Average Score
3. Score Parameter Wise
4. Strengths
5. Improvement Areas
6. Learnings

## Model switching from Streamlit Secrets

No code edit is needed to change the GPT model. Change this line in Streamlit Secrets:

```toml
OPENAI_MODEL = "gpt-5.5"
```

When you want a lower-cost model, change only the value, for example:

```toml
OPENAI_MODEL = "gpt-5.4"
```

Then reboot/redeploy the Streamlit app.

## Required files to replace

Replace these files in GitHub:

```text
app.py
supabase_client.py
email_sender.py
scoring_prompt.py
supabase_migration.sql
README.md
.env.example
```

Other files can stay as they are.

## Supabase setup

After replacing files in GitHub, open Supabase SQL Editor and run:

```text
supabase_migration.sql
```

This will simplify the `call_scores` table so only the final requested columns remain.

## Streamlit Secrets

```toml
DEEPGRAM_API_KEY = "your_deepgram_key_here"
OPENAI_API_KEY = "your_openai_key_here"
OPENAI_MODEL = "gpt-5.5"
OPENAI_REASONING_EFFORT = "xhigh"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your_supabase_key_here"
SENDER_EMAIL = "creativedits123@gmail.com"
SENDER_PASSWORD = "your_gmail_app_password_here"
RECIPIENT_EMAILS = "extrastuff0980@gmail.com"
DASHBOARD_PASSWORD = "show123"
MAX_PARALLEL_CALLS = "5"
```

## Tone + Truth failure detail

If Tone + Truth fails, the report will now show:

- whether Tone failed, Truth failed, or both failed
- what the student partner said or did
- why it failed
- what should have been said or done instead

When Tone + Truth fails, the remaining parameters are not evaluated and Average Score is `0.0`.
