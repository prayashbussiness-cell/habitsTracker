-- v7: run ONCE in Supabase > SQL Editor on your existing project.
-- (New installs already get this from schema.sql.)
-- Remembers the day an unfinished task was carried over from, so the app can show a "from Nov 11" badge.
-- The app still works without it (tasks still roll over), only the badge is missing.
alter table daily_tasks add column if not exists carried_from date;
