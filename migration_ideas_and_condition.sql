-- Run once in Supabase > SQL Editor (existing projects). Adds the Ideas page and Body condition tracker tables.
create table if not exists ideas (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  name text not null,
  details text not null default '',
  time_required text not null default '',
  advantage text not null default '',
  skipped boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists ideas_user on ideas(user_id);

-- One row per user per day. mood = mood index, body_strength = body condition, both 0-10.
create table if not exists body_condition (
  user_id uuid not null references users(id) on delete cascade,
  log_date date not null,
  mood int check (mood between 0 and 10),
  body_strength int check (body_strength between 0 and 10),
  updated_at timestamptz not null default now(),
  primary key (user_id, log_date)
);

alter table ideas enable row level security;
alter table body_condition enable row level security;
