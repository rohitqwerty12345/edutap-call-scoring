# EduTap EPFO Call Scoring System

This Streamlit app processes EduTap EPFO call recordings and produces AI-based call-quality scores.

## Final scoring parameters

The final dashboard/report names are:

1. Guardrails
2. Opening
3. Discovery
4. Evidence
5. Personal Urgency
6. Real Hesitation Reason
7. Clear Next Step

## Final call types

The AI now classifies every call into one of these types:

| Call type | Meaning | Output |
|---|---|---|
| `full_analysis` | Real conversation happened about exam, course, student situation, preparation, objection, or buying decision. | Scores all applicable parameters. |
| `follow_up_only` | Student was busy/could not talk, but student partner handled follow-up enough to judge the ending. | Scores only Guardrails and Clear Next Step. |
| `not_worthy` | No real conversation and no meaningful follow-up handling. | Saves row as not worthy. |

## Guardrails hard-stop rule

If Guardrails fails, the call receives zero score. The AI does not analyze the remaining parameters. This is intentional because honesty and student respect are the floor of the call.

## What the app does

1. Support team uploads MP3/WAV/M4A call recordings in Streamlit.
2. The app extracts the student mobile number from the file name.
3. The audio goes to Deepgram Nova-3 Hindi with diarization enabled.
4. The transcript goes to OpenAI using the final scoring prompt.
5. The JSON result is saved in Supabase.
6. Audio and transcript are uploaded to Supabase Storage.
7. A password-protected dashboard shows results.
8. An Excel report is emailed after the batch finishes.

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
├── supabase_migration.sql
├── .env.example
└── README.md
```

## 1. Supabase setup

Open Supabase SQL Editor and run:

```text
supabase_migration.sql
```

This creates/updates:

- `call_scores` table
- final database columns using the final parameter names
- public `call-recordings` storage bucket
- public `call-transcripts` storage bucket
- useful indexes for dashboard loading

For quick testing, either disable Row Level Security on `call_scores` or use a Supabase service-role key as `SUPABASE_KEY`.

## Final important database columns

Main identifiers:

```text
student_number
call_type
call_audio_link
call_transcript
call_transcript_link
analysis_worthy
converted_status
ai_output_json
```

Parameter score columns:

```text
guardrails
opening_score
discovery_score
evidence_score
personal_urgency_score
real_hesitation_reason_score
clear_next_step_score
overall_score
```

Detailed columns are also created for quotes, reasons, and explanations for every parameter.

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
MAX_PARALLEL_CALLS=5
```

For Gmail, `SENDER_PASSWORD` must be a Gmail App Password, not the normal Gmail password.

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

1. Push all files to GitHub.
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
MAX_PARALLEL_CALLS = "5"
```

## Important test checklist

Before giving the app to the support team, test 3 real calls:

- one full conversation
- one busy/call-later conversation
- one not-worthy call

Verify:

- Transcript is generated.
- Speaker mapping is correct.
- OpenAI returns valid JSON or exact `not_worthy`.
- Supabase row is created.
- Audio link opens.
- Transcript link opens.
- Dashboard shows final parameter names.
- Excel report uses final parameter names.
- Guardrails fail gives zero score.
- Follow-up-only call scores only Clear Next Step.

## Speaker mapping warning

Deepgram assigns `Speaker 0` to whoever speaks first. This code assumes the student partner speaks first.

If test recordings show the student is labeled as Speaker A, swap the labels in `_speaker_label()` inside `deepgram_client.py`.
