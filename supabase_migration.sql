-- EduTap EPFO Call Scoring final database migration
-- Run this in Supabase SQL Editor before testing the final app.

create extension if not exists pgcrypto;

-- Public storage buckets used by the app.
insert into storage.buckets (id, name, public)
values ('call-recordings', 'call-recordings', true)
on conflict (id) do update set public = true;

insert into storage.buckets (id, name, public)
values ('call-transcripts', 'call-transcripts', true)
on conflict (id) do update set public = true;

create table if not exists public.call_scores (
  id uuid default gen_random_uuid() primary key,
  created_at timestamptz default now()
);

alter table public.call_scores add column if not exists student_number text;
alter table public.call_scores add column if not exists call_type text;
alter table public.call_scores add column if not exists call_audio_link text;
alter table public.call_scores add column if not exists call_transcript text;
alter table public.call_scores add column if not exists call_transcript_link text;
alter table public.call_scores add column if not exists analysis_worthy boolean default true;
alter table public.call_scores add column if not exists converted_status text;
alter table public.call_scores add column if not exists ai_output_json jsonb;

-- Guardrails
alter table public.call_scores add column if not exists guardrails text;
alter table public.call_scores add column if not exists guardrails_reason text;
alter table public.call_scores add column if not exists guardrails_false_information_detail text;

-- Opening
alter table public.call_scores add column if not exists opening_score text;
alter table public.call_scores add column if not exists opening_what_student_partner_said_right_after_intro text;
alter table public.call_scores add column if not exists opening_quote text;
alter table public.call_scores add column if not exists opening_specific_to_student_trial_activity text;
alter table public.call_scores add column if not exists opening_why_this_score text;

-- Discovery
alter table public.call_scores add column if not exists discovery_score text;
alter table public.call_scores add column if not exists discovery_questions_asked_by_student_partner text;
alter table public.call_scores add column if not exists discovery_information_student_volunteered_unprompted text;
alter table public.call_scores add column if not exists discovery_what_student_partner_found_out text;
alter table public.call_scores add column if not exists discovery_quality_assessment text;
alter table public.call_scores add column if not exists discovery_credit_assessment text;
alter table public.call_scores add column if not exists discovery_student_said_own_problem_out_loud text;
alter table public.call_scores add column if not exists discovery_best_discovery_moment_quote text;
alter table public.call_scores add column if not exists discovery_why_this_score text;

-- Evidence
alter table public.call_scores add column if not exists evidence_score text;
alter table public.call_scores add column if not exists evidence_discovery_finding_used text;
alter table public.call_scores add column if not exists evidence_master_course_feature_connected text;
alter table public.call_scores add column if not exists evidence_factually_accurate_about_master_course text;
alter table public.call_scores add column if not exists evidence_inaccuracy_detail text;
alter table public.call_scores add column if not exists evidence_quote text;
alter table public.call_scores add column if not exists evidence_why_this_score text;

-- Personal Urgency
alter table public.call_scores add column if not exists personal_urgency_score text;
alter table public.call_scores add column if not exists personal_urgency_source_of_urgency text;
alter table public.call_scores add column if not exists personal_urgency_student_situation_used text;
alter table public.call_scores add column if not exists personal_urgency_quote text;
alter table public.call_scores add column if not exists personal_urgency_why_this_score text;

-- Real Hesitation Reason
alter table public.call_scores add column if not exists real_hesitation_reason_score text;
alter table public.call_scores add column if not exists real_hesitation_reason_na boolean default false;
alter table public.call_scores add column if not exists real_hesitation_reason_objection_raised_by_student text;
alter table public.call_scores add column if not exists real_hesitation_reason_surface_reason_stated text;
alter table public.call_scores add column if not exists real_hesitation_reason_real_reason_found text;
alter table public.call_scores add column if not exists real_hesitation_reason_quote_of_attempt text;
alter table public.call_scores add column if not exists real_hesitation_reason_why_this_score text;

-- Clear Next Step
alter table public.call_scores add column if not exists clear_next_step_score text;
alter table public.call_scores add column if not exists clear_next_step_what_happened_at_end text;
alter table public.call_scores add column if not exists clear_next_step_payment_link_sent text;
alter table public.call_scores add column if not exists clear_next_step_followup_date_and_time_agreed text;
alter table public.call_scores add column if not exists clear_next_step_course_details_sent_on_whatsapp text;
alter table public.call_scores add column if not exists clear_next_step_quote_of_closing_line text;
alter table public.call_scores add column if not exists clear_next_step_why_this_score text;

-- Overall
alter table public.call_scores add column if not exists overall_score text;
alter table public.call_scores add column if not exists overall_guardrails text;
alter table public.call_scores add column if not exists overall_opening text;
alter table public.call_scores add column if not exists overall_discovery text;
alter table public.call_scores add column if not exists overall_evidence text;
alter table public.call_scores add column if not exists overall_personal_urgency text;
alter table public.call_scores add column if not exists overall_real_hesitation_reason text;
alter table public.call_scores add column if not exists overall_clear_next_step text;
alter table public.call_scores add column if not exists overall_total text;
alter table public.call_scores add column if not exists overall_percentage text;
alter table public.call_scores add column if not exists guardrails_review_flag text;

-- Coaching/output
alter table public.call_scores add column if not exists top_strength text;
alter table public.call_scores add column if not exists biggest_improvement_area text;
alter table public.call_scores add column if not exists coaching_note text;

create index if not exists idx_call_scores_created_at on public.call_scores (created_at desc);
create index if not exists idx_call_scores_student_number on public.call_scores (student_number);
create index if not exists idx_call_scores_call_type on public.call_scores (call_type);
create index if not exists idx_call_scores_guardrails on public.call_scores (guardrails);
