-- v6: run ONCE in Supabase > SQL Editor on your existing project, BEFORE using the new version.
-- (New installs already get this from schema.sql.)

-- Ego page: ranked cards with colour, border colour, hours, category and priority
create table if not exists ego_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  name text not null,
  category text not null default 'Other',
  priority text not null default 'med' check (priority in ('high','med','low')),
  description text,
  done boolean not null default false,
  hours numeric not null default 0 check (hours >= 0),
  color text not null default '#CFA8D5' check (color ~ '^#[0-9a-fA-F]{6}$'),   -- colour of the card name / swatch
  border text not null default 'none' check (border in ('none','red','green')), -- border colour of the box
  rank int not null default 0,                                                   -- 1 = top of the list
  created_at timestamptz not null default now()
);
create index if not exists ego_items_user_rank on ego_items(user_id, rank);
alter table ego_items enable row level security;

-- Make the API see the new table right away
notify pgrst, 'reload schema';
