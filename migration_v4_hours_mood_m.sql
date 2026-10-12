-- v4: run ONCE in Supabase > SQL Editor on your existing project, BEFORE using the new version.
-- (New installs already get these columns from schema.sql.)

-- 1. Hours spent on each task
alter table daily_tasks add column if not exists hours numeric not null default 0 check (hours >= 0);

-- 2. Mood index (0-10) for each habit, per day
alter table daily_habit_progress add column if not exists mood int check (mood between 0 and 10);

-- 3. Daily "M" counter (stored with the body condition row for that day)
alter table body_condition add column if not exists m_count int not null default 0 check (m_count >= 0);

-- Make the API see the new columns right away
notify pgrst, 'reload schema';
