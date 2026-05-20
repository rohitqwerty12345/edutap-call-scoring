# EduTap EPFO Call Scoring System

This Streamlit app processes EduTap EPFO sales/support call recordings and produces call-quality scores.

## What it does

1. Upload MP3/WAV/M4A call recordings in Streamlit.
2. Send each call to Deepgram for Hindi/Hinglish transcription with diarization.
3. Send each transcript to OpenAI `gpt-5.5` with `xhigh` reasoning for scoring.
4. Save results in Supabase.
5. Show a password-protected dashboard in Streamlit.
6. Email an Excel report after the batch finishes.

## File structure

```text
edutap-call-scoring/
├── app.py
├── pipeline.py
├── deepgram_client.py
├── openai_client.py
├── supabase_client.py
├── email_sender.py
├── scoring_prompt.py
├── requirements.txt
├── .env.example
└── README.md
```

## 1. Create Supabase table

Run this SQL in your Supabase SQL editor:

```sql
create table call_scores (
  id uuid default gen_random_uuid() primary key,
  created_at timestamptz default now(),
  student_number text,
  call_audio_link text,
  call_transcript text,
  guardrails text,
  opening_score text,
  discovery_score text,
  evidence_score text,
  resonance_score text,
  diagnosis_score text,
  closure_score text,
  overall_score text,
  top_strength text,
  biggest_improvement_area text,
  coaching_note text,
  analysis_worthy boolean default true
);
```

For quick testing, either disable Row Level Security on this table or use a Supabase service-role key in `SUPABASE_KEY`.

## 2. Install locally

```bash
pip install -r requirements.txt
```

## 3. Create `.env`

```bash
cp .env.example .env
```

Fill in:

```text
DEEPGRAM_API_KEY=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.5
OPENAI_REASONING_EFFORT=xhigh
SUPABASE_URL=
SUPABASE_KEY=
SENDER_EMAIL=creativedits123@gmail.com
SENDER_PASSWORD=
RECIPIENT_EMAILS=extrastuff0980@gmail.com
DASHBOARD_PASSWORD=show123
```

For Gmail, `SENDER_PASSWORD` must be a Gmail App Password, not the normal Gmail login password.

## 4. Run locally

```bash
streamlit run app.py
```

## 5. Upload file naming format

Recommended format:

```text
xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx_7974141508.mp3
```

The app extracts the student mobile number from the digits after the final underscore.

It also has a fallback that extracts any 10-digit number from the filename.

## 6. Deploy to Streamlit Cloud

1. Push these files to GitHub.
2. Open Streamlit Cloud.
3. Create a new app from the GitHub repo.
4. Add secrets in Streamlit Cloud settings.

Use this format in Streamlit Secrets:

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
```

## Important test checklist

Before giving the app to the support team, test one real call and verify:

- Transcript is correctly generated.
- Speaker mapping is correct:
  - Speaker A = Agent
  - Speaker B = Student
- OpenAI returns valid JSON.
- Supabase row is created.
- Dashboard shows the row.
- Email report arrives with an Excel attachment.

## Speaker mapping warning

Deepgram assigns `Speaker 0` to whoever speaks first. This code assumes the agent speaks first.

If test recordings show the student is labeled as Speaker A, swap the labels in `_speaker_label()` inside `deepgram_client.py`.


## Required Supabase migration for expanded dashboard

Before testing this version, open Supabase SQL Editor and run the contents of:

```text
supabase_migration.sql
```

This adds:
- call transcript link
- converted status
- detailed GPT output columns
- raw AI JSON storage
- public Storage buckets for call recordings and transcripts
