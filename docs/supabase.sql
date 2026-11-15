-- FINN optional accounts: run once in Supabase → SQL Editor.
-- One row per user. Row-level security means a signed-in user can only ever
-- read or write their own row, which is why the public anon key is safe in the app.
create table if not exists public.user_prefs (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  followed   text[]      not null default '{}',
  settings   jsonb       not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.user_prefs enable row level security;

create policy "read own prefs"   on public.user_prefs for select using (auth.uid() = user_id);
create policy "insert own prefs" on public.user_prefs for insert with check (auth.uid() = user_id);
create policy "update own prefs" on public.user_prefs for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
