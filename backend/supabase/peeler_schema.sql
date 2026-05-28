-- PaperLens Paper Peeler V1 schema.
-- Run this in Supabase SQL Editor before setting PEELER_STORAGE=supabase.

create extension if not exists vector;

create table if not exists public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text,
  plan text not null default 'free' check (plan in ('free', 'pro', 'team')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.user_usage (
  user_id uuid primary key references auth.users(id) on delete cascade,
  plan text not null default 'free' check (plan in ('free', 'pro', 'team')),
  new_peels_used int not null default 0,
  chat_messages_used int not null default 0,
  failed_jobs_count int not null default 0,
  period_start timestamptz not null default now(),
  period_end timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists public.papers (
  paper_id text primary key,
  canonical_id text not null unique,
  source_type text not null check (source_type in ('arxiv', 'doi', 'title', 'pdf_upload', 'feed', 'private_upload')),
  title text not null,
  authors jsonb not null default '[]'::jsonb,
  abstract text not null default '',
  source_url text,
  pdf_url text,
  arxiv_id text,
  doi text,
  published_at text,
  topic text not null default 'General_AI',
  difficulty text not null default 'Intermediate',
  confidence text not null default 'medium',
  extraction_quality text,
  is_private boolean not null default false,
  has_peeler boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.paper_chunks (
  chunk_id text primary key,
  paper_id text not null references public.papers(paper_id) on delete cascade,
  section text not null,
  text text not null,
  page_start int,
  page_end int,
  extraction_quality text not null default 'medium',
  embedding vector(1536),
  created_at timestamptz not null default now()
);

create index if not exists paper_chunks_paper_id_idx on public.paper_chunks(paper_id);
create index if not exists paper_chunks_embedding_idx on public.paper_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

create table if not exists public.peel_outputs (
  paper_id text primary key references public.papers(paper_id) on delete cascade,
  schema_version text not null default '1.0',
  sections_json jsonb not null,
  architecture_json jsonb not null,
  math_peel_json jsonb not null default '[]'::jsonb,
  related_papers_json jsonb not null default '[]'::jsonb,
  suggested_questions jsonb not null default '[]'::jsonb,
  model_used text not null default 'unknown',
  completed_from_cache boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.peel_jobs (
  job_id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  paper_id text,
  status text not null,
  stage text not null default 'queued',
  progress int not null default 0,
  error_code text,
  error_message text,
  thread_id text,
  completed_from_cache boolean not null default false,
  consumed_credit boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists peel_jobs_user_id_idx on public.peel_jobs(user_id);

create table if not exists public.user_threads (
  thread_id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  paper_id text not null references public.papers(paper_id) on delete cascade,
  peel_output_id text not null references public.peel_outputs(paper_id) on delete cascade,
  title text not null default '',
  created_at timestamptz not null default now()
);

create index if not exists user_threads_user_id_idx on public.user_threads(user_id);
create index if not exists user_threads_paper_id_idx on public.user_threads(paper_id);

create table if not exists public.chat_messages (
  id bigint generated always as identity primary key,
  thread_id text not null references public.user_threads(thread_id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  retrieved_chunk_ids jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists chat_messages_thread_id_idx on public.chat_messages(thread_id, created_at);

create table if not exists public.subscriptions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  provider text,
  provider_customer_id text,
  provider_subscription_id text,
  status text not null default 'inactive',
  plan text not null default 'free',
  current_period_end timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;
alter table public.user_usage enable row level security;
alter table public.papers enable row level security;
alter table public.paper_chunks enable row level security;
alter table public.peel_outputs enable row level security;
alter table public.peel_jobs enable row level security;
alter table public.user_threads enable row level security;
alter table public.chat_messages enable row level security;
alter table public.subscriptions enable row level security;

drop policy if exists "profiles own row" on public.profiles;
create policy "profiles own row" on public.profiles
  for select using (auth.uid() = user_id);

drop policy if exists "usage own row" on public.user_usage;
create policy "usage own row" on public.user_usage
  for select using (auth.uid() = user_id);

drop policy if exists "public peeled papers readable" on public.papers;
create policy "public peeled papers readable" on public.papers
  for select using (is_private = false or exists (
    select 1 from public.user_threads t
    where t.paper_id = papers.paper_id and t.user_id = auth.uid()
  ));

drop policy if exists "public peel outputs readable" on public.peel_outputs;
create policy "public peel outputs readable" on public.peel_outputs
  for select using (exists (
    select 1 from public.papers p
    where p.paper_id = peel_outputs.paper_id and p.is_private = false
  ) or exists (
    select 1 from public.user_threads t
    where t.peel_output_id = peel_outputs.paper_id and t.user_id = auth.uid()
  ));

drop policy if exists "own jobs readable" on public.peel_jobs;
create policy "own jobs readable" on public.peel_jobs
  for select using (auth.uid() = user_id);

drop policy if exists "own threads readable" on public.user_threads;
create policy "own threads readable" on public.user_threads
  for select using (auth.uid() = user_id);

drop policy if exists "own messages readable" on public.chat_messages;
create policy "own messages readable" on public.chat_messages
  for select using (exists (
    select 1 from public.user_threads t
    where t.thread_id = chat_messages.thread_id and t.user_id = auth.uid()
  ));

drop policy if exists "own subscriptions readable" on public.subscriptions;
create policy "own subscriptions readable" on public.subscriptions
  for select using (auth.uid() = user_id);
