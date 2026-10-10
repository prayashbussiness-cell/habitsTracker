-- Start Your Day: run this once in Supabase > SQL Editor.
create extension if not exists pgcrypto;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  phone text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists habit_cards (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  name text not null,
  category text not null default 'Other',
  target numeric not null check (target > 0),
  unit text not null default 'hour',
  icon text not null default 'book',
  description text,
  starts_on date not null default current_date,
  created_at timestamptz not null default now()
);

create table if not exists daily_tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  task_date date not null,
  name text not null,
  category text not null default 'Other',
  priority text not null default 'med' check (priority in ('high','med','low')),
  description text,
  done boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists daily_tasks_user_date on daily_tasks(user_id, task_date);

create table if not exists daily_habit_progress (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  card_id uuid not null references habit_cards(id) on delete cascade,
  progress_date date not null,
  actual numeric not null default 0 check (actual >= 0),
  note text,
  skipped boolean not null default false,
  unique (card_id, progress_date)
);
create index if not exists dhp_user_date on daily_habit_progress(user_id, progress_date);

create table if not exists daily_notes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  note_date date not null,
  note text not null default '',
  unique (user_id, note_date)
);

create table if not exists goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  name text not null,
  progress int not null default 0 check (progress between 0 and 100),
  created_at timestamptz not null default now()
);

create table if not exists daily_statistics (
  user_id uuid not null references users(id) on delete cascade,
  stat_date date not null,
  tasks_done int not null default 0,
  tasks_total int not null default 0,
  habits_done int not null default 0,
  habits_total int not null default 0,
  habits_skipped int not null default 0,
  task_pct int not null default 0,
  efficiency int not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, stat_date)
);

-- Ideas page + body condition tracker
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


-- The browser never talks to Supabase. Only the FastAPI server (service_role key) does,
-- so lock every table down for the public anon key.
alter table users enable row level security;
alter table habit_cards enable row level security;
alter table daily_tasks enable row level security;
alter table daily_habit_progress enable row level security;
alter table daily_notes enable row level security;
alter table goals enable row level security;
alter table daily_statistics enable row level security;
alter table ideas enable row level security;
alter table body_condition enable row level security;
