-- v5: run ONCE in Supabase > SQL Editor on your existing project, BEFORE using the new version.
-- (New installs already get all of this from schema.sql.)

-- 1. Overall story of the day (dropdown under "START YOUR DAY") + the "God" counter, stored per day
alter table body_condition add column if not exists story text
  check (story is null or story in ('fight','messed','won','leave','frustrated'));
alter table body_condition add column if not exists god_count int not null default 0 check (god_count >= 0);

-- 2. Monthly Target cards (Aug / Sept / Oct pages): task-like rows, grouped by month ("YYYY-MM")
create table if not exists monthly_targets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  month text not null check (month ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  name text not null,
  category text not null default 'Other',
  priority text not null default 'med' check (priority in ('high','med','low')),
  description text,
  done boolean not null default false,
  hours numeric not null default 0 check (hours >= 0),
  created_at timestamptz not null default now()
);
create index if not exists monthly_targets_user_month on monthly_targets(user_id, month);
alter table monthly_targets enable row level security;

-- Make the API see the new columns / table right away
notify pgrst, 'reload schema';
