-- EduTap final simplified call_scores table
-- This keeps ONLY the final dashboard/database columns requested.
-- Run once in Supabase SQL Editor after replacing the code files.

create extension if not exists pgcrypto;

insert into storage.buckets (id, name, public)
values ('call-recordings', 'call-recordings', true)
on conflict (id) do update set public = true;

insert into storage.buckets (id, name, public)
values ('call-transcripts', 'call-transcripts', true)
on conflict (id) do update set public = true;

create table if not exists public.call_scores (
  "Date" date default current_date,
  "Student Number" text,
  "Call Type" text,
  "Call Recording Link" text,
  "Converted Status" text,
  "Average Score" text,
  "Score Parameter Wise" text,
  "Strengths" text,
  "Improvement Areas" text,
  "Learnings" text,
  "Transcript Link" text
);

alter table public.call_scores add column if not exists "Date" date;

-- Keep Date as date-only, not timestamp.
alter table public.call_scores
  alter column "Date" type date
  using ("Date"::date);
alter table public.call_scores add column if not exists "Student Number" text;
alter table public.call_scores add column if not exists "Call Type" text;
alter table public.call_scores add column if not exists "Call Recording Link" text;
alter table public.call_scores add column if not exists "Converted Status" text;
alter table public.call_scores add column if not exists "Average Score" text;
alter table public.call_scores add column if not exists "Score Parameter Wise" text;
alter table public.call_scores add column if not exists "Strengths" text;
alter table public.call_scores add column if not exists "Improvement Areas" text;
alter table public.call_scores add column if not exists "Learnings" text;
alter table public.call_scores add column if not exists "Transcript Link" text;

-- Best-effort migration from older column names into the final columns.
do $$
begin
  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='created_at') then
    execute 'update public.call_scores set "Date" = coalesce("Date", created_at::date)';
  end if;
  execute 'update public.call_scores set "Date" = coalesce("Date", current_date)';

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='student_number') then
    execute 'update public.call_scores set "Student Number" = coalesce("Student Number", student_number)';
  end if;

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='call_type') then
    execute 'update public.call_scores set "Call Type" = coalesce("Call Type", call_type)';
  end if;
  execute 'update public.call_scores set "Call Type" = coalesce("Call Type", ''full_analysis'')';

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='call_audio_link') then
    execute 'update public.call_scores set "Call Recording Link" = coalesce("Call Recording Link", call_audio_link)';
  end if;

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='converted_status') then
    execute 'update public.call_scores set "Converted Status" = coalesce("Converted Status", converted_status)';
  end if;
  execute 'update public.call_scores set "Converted Status" = coalesce("Converted Status", ''Not converted'')';

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='overall_score') then
    execute 'update public.call_scores set "Average Score" = coalesce("Average Score", overall_score)';
  end if;

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='top_strength') then
    execute 'update public.call_scores set "Strengths" = coalesce("Strengths", top_strength)';
  end if;

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='biggest_improvement_area') then
    execute 'update public.call_scores set "Improvement Areas" = coalesce("Improvement Areas", biggest_improvement_area)';
  end if;

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='coaching_note') then
    execute 'update public.call_scores set "Learnings" = coalesce("Learnings", coaching_note)';
  end if;

  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='call_scores' and column_name='call_transcript_link') then
    execute 'update public.call_scores set "Transcript Link" = coalesce("Transcript Link", call_transcript_link)';
  end if;
end $$;

-- Drop every old/extra column so only the final requested columns remain.
do $$
declare
  col record;
  keep_cols text[] := array[
    'Date',
    'Student Number',
    'Call Type',
    'Call Recording Link',
    'Converted Status',
    'Average Score',
    'Score Parameter Wise',
    'Strengths',
    'Improvement Areas',
    'Learnings',
    'Transcript Link'
  ];
begin
  for col in
    select column_name
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'call_scores'
      and not (column_name = any (keep_cols))
  loop
    execute format('alter table public.call_scores drop column if exists %I cascade', col.column_name);
  end loop;
end $$;

alter table public.call_scores alter column "Date" set default current_date;

create index if not exists idx_call_scores_final_date on public.call_scores ("Date" desc);
create index if not exists idx_call_scores_final_student_number on public.call_scores ("Student Number");
create index if not exists idx_call_scores_final_call_type on public.call_scores ("Call Type");

-- Normalize Average Score to plain number only: "3.0", not "3.0/10 (30%)" or "19/60".
do $$
declare
  r record;
  numerator numeric;
  denominator numeric;
  new_score text;
begin
  for r in select ctid, "Average Score" as score_text from public.call_scores loop
    if r.score_text is null or trim(r.score_text) = '' then
      continue;
    end if;

    if r.score_text ~ '^\s*\d+(\.\d+)?\s*/\s*\d+(\.\d+)?' then
      numerator := (regexp_match(r.score_text, '(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)'))[1]::numeric;
      denominator := (regexp_match(r.score_text, '(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)'))[2]::numeric;
      if denominator > 0 then
        new_score := to_char((numerator / denominator) * 10, 'FM999990.0');
        update public.call_scores set "Average Score" = new_score where ctid = r.ctid;
      end if;
    elsif r.score_text ~ '^\s*\d+(\.\d+)?\s*$' then
      new_score := to_char(trim(r.score_text)::numeric, 'FM999990.0');
      update public.call_scores set "Average Score" = new_score where ctid = r.ctid;
    end if;
  end loop;
end $$;



-- Normalize visible parameter names in stored text columns to the final names.
do $$
begin
  update public.call_scores
  set "Score Parameter Wise" = replace(replace(replace(replace(replace(replace(replace(replace("Score Parameter Wise", 'Guardrails', 'Tone + Truth'), 'Resonance', 'Personal Urgency'), 'Diagnosis', 'Hesitation Discovery'), 'Closure', 'Next Step Clarity'), 'Real Hesitation Reason', 'Hesitation Discovery'), 'Clear Next Step', 'Next Step Clarity'), 'Discovery', 'Pain Point Discovery'), 'Hesitation Pain Point Discovery', 'Hesitation Discovery')
  where "Score Parameter Wise" is not null;

  update public.call_scores
  set "Strengths" = replace(replace(replace(replace(replace(replace(replace(replace("Strengths", 'Guardrails', 'Tone + Truth'), 'Resonance', 'Personal Urgency'), 'Diagnosis', 'Hesitation Discovery'), 'Closure', 'Next Step Clarity'), 'Real Hesitation Reason', 'Hesitation Discovery'), 'Clear Next Step', 'Next Step Clarity'), 'Discovery', 'Pain Point Discovery'), 'Hesitation Pain Point Discovery', 'Hesitation Discovery')
  where "Strengths" is not null;

  update public.call_scores
  set "Improvement Areas" = replace(replace(replace(replace(replace(replace(replace(replace("Improvement Areas", 'Guardrails', 'Tone + Truth'), 'Resonance', 'Personal Urgency'), 'Diagnosis', 'Hesitation Discovery'), 'Closure', 'Next Step Clarity'), 'Real Hesitation Reason', 'Hesitation Discovery'), 'Clear Next Step', 'Next Step Clarity'), 'Discovery', 'Pain Point Discovery'), 'Hesitation Pain Point Discovery', 'Hesitation Discovery')
  where "Improvement Areas" is not null;

  update public.call_scores
  set "Learnings" = replace(replace(replace(replace(replace(replace(replace(replace("Learnings", 'Guardrails', 'Tone + Truth'), 'Resonance', 'Personal Urgency'), 'Diagnosis', 'Hesitation Discovery'), 'Closure', 'Next Step Clarity'), 'Real Hesitation Reason', 'Hesitation Discovery'), 'Clear Next Step', 'Next Step Clarity'), 'Discovery', 'Pain Point Discovery'), 'Hesitation Pain Point Discovery', 'Hesitation Discovery')
  where "Learnings" is not null;

  -- Fix accidental double replacement if the migration is run more than once.
  update public.call_scores
  set "Score Parameter Wise" = replace("Score Parameter Wise", 'Pain Point Pain Point Discovery', 'Pain Point Discovery')
  where "Score Parameter Wise" is not null;
  update public.call_scores
  set "Strengths" = replace("Strengths", 'Pain Point Pain Point Discovery', 'Pain Point Discovery')
  where "Strengths" is not null;
  update public.call_scores
  set "Improvement Areas" = replace("Improvement Areas", 'Pain Point Pain Point Discovery', 'Pain Point Discovery')
  where "Improvement Areas" is not null;
  update public.call_scores
  set "Learnings" = replace("Learnings", 'Pain Point Pain Point Discovery', 'Pain Point Discovery')
  where "Learnings" is not null;
end $$;

-- Backend processing queue tables for GitHub Actions worker.
create table if not exists public.call_processing_batches (
  batch_id text primary key,
  created_at timestamptz default now(),
  completed_at timestamptz,
  status text default 'pending',
  total_files integer default 0,
  completed_files integer default 0,
  failed_files integer default 0,
  report_sent boolean default false,
  error_email_sent boolean default false,
  last_error text
);

create table if not exists public.call_processing_jobs (
  id uuid primary key default gen_random_uuid(),
  batch_id text references public.call_processing_batches(batch_id) on delete cascade,
  created_at timestamptz default now(),
  started_at timestamptz,
  completed_at timestamptz,
  status text default 'pending',
  student_number text,
  audio_filename text,
  audio_storage_path text,
  audio_public_url text,
  attempt_count integer default 0,
  error_message text,
  saved_row_json jsonb
);

alter table public.call_processing_batches add column if not exists completed_at timestamptz;
alter table public.call_processing_batches add column if not exists status text default 'pending';
alter table public.call_processing_batches add column if not exists total_files integer default 0;
alter table public.call_processing_batches add column if not exists completed_files integer default 0;
alter table public.call_processing_batches add column if not exists failed_files integer default 0;
alter table public.call_processing_batches add column if not exists report_sent boolean default false;
alter table public.call_processing_batches add column if not exists error_email_sent boolean default false;
alter table public.call_processing_batches add column if not exists last_error text;

alter table public.call_processing_jobs add column if not exists started_at timestamptz;
alter table public.call_processing_jobs add column if not exists completed_at timestamptz;
alter table public.call_processing_jobs add column if not exists status text default 'pending';
alter table public.call_processing_jobs add column if not exists student_number text;
alter table public.call_processing_jobs add column if not exists audio_filename text;
alter table public.call_processing_jobs add column if not exists audio_storage_path text;
alter table public.call_processing_jobs add column if not exists audio_public_url text;
alter table public.call_processing_jobs add column if not exists attempt_count integer default 0;
alter table public.call_processing_jobs add column if not exists error_message text;
alter table public.call_processing_jobs add column if not exists saved_row_json jsonb;

create index if not exists idx_call_processing_jobs_status_created on public.call_processing_jobs (status, created_at);
create index if not exists idx_call_processing_jobs_batch on public.call_processing_jobs (batch_id);
create index if not exists idx_call_processing_batches_created on public.call_processing_batches (created_at desc);
create index if not exists idx_call_processing_batches_status on public.call_processing_batches (status);
