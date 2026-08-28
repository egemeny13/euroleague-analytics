-- migrations/0016_mcp_row_budget.up.sql
--
-- A short-lived usage ledger plus a daily aggregate makes a caller's row
-- allowance durable across process restarts without retaining a call history
-- forever. The aggregate and ledger are both expired after 31 days.

create role el_usage_writer with login;

create table public.mcp_row_budget_policy (
    subject text primary key,
    daily_row_limit integer not null check (daily_row_limit > 0)
);

create table public.mcp_row_daily_budget (
    subject text not null,
    usage_date date not null,
    rows_used integer not null check (rows_used >= 0),
    primary key (subject, usage_date)
);

create table public.mcp_row_usage (
    operation_id uuid primary key,
    subject text not null,
    usage_date date not null,
    operation text not null check (operation in ('reserve', 'settle')),
    row_delta integer not null,
    daily_row_limit integer not null,
    remaining_rows integer not null,
    created_at timestamptz not null default current_timestamp
);

comment on table public.mcp_row_budget_policy is
    'Per-subject daily row limits. Subjects without a row use the documented 50000-row default.';
comment on table public.mcp_row_daily_budget is
    'Daily aggregate usage, expired after 31 days by each usage operation.';

alter table public.mcp_row_budget_policy enable row level security;
alter table public.mcp_row_daily_budget enable row level security;
alter table public.mcp_row_usage enable row level security;

create function public.apply_mcp_row_usage()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    daily_limit integer;
    used_rows integer;
begin
    if new.usage_date <> (current_timestamp at time zone 'UTC')::date then
        raise exception 'row budget operations must use the current UTC date';
    end if;

    delete from public.mcp_row_usage
    where usage_date < (current_timestamp at time zone 'UTC')::date - 31;
    delete from public.mcp_row_daily_budget
    where usage_date < (current_timestamp at time zone 'UTC')::date - 31;

    select coalesce(
        (select daily_row_limit from public.mcp_row_budget_policy where subject = new.subject),
        50000
    ) into daily_limit;

    insert into public.mcp_row_daily_budget (subject, usage_date, rows_used)
    values (new.subject, new.usage_date, 0)
    on conflict (subject, usage_date) do nothing;

    select rows_used into used_rows
    from public.mcp_row_daily_budget
    where subject = new.subject and usage_date = new.usage_date
    for update;

    if new.operation = 'reserve' and new.row_delta <= 0 then
        raise exception 'a row budget reservation must be positive';
    end if;
    if new.operation = 'settle' and new.row_delta > 0 then
        raise exception 'a row budget settlement cannot increase usage';
    end if;
    if used_rows + new.row_delta > daily_limit then
        raise exception 'daily row budget exhausted';
    end if;

    update public.mcp_row_daily_budget
    set rows_used = used_rows + new.row_delta
    where subject = new.subject and usage_date = new.usage_date;

    new.daily_row_limit := daily_limit;
    new.remaining_rows := daily_limit - used_rows - new.row_delta;
    return new;
end;
$$;

create trigger apply_mcp_row_usage_before_insert
before insert on public.mcp_row_usage
for each row execute function public.apply_mcp_row_usage();

-- A dedicated writer may insert ledger operations only. The security-definer
-- trigger performs the bounded aggregate update; no application credential can
-- read, update, or delete the usage data.
grant connect on database postgres to el_usage_writer;
grant usage on schema public to el_usage_writer;
grant insert on table public.mcp_row_usage to el_usage_writer;

create policy mcp_row_usage_writer_inserts_only
on public.mcp_row_usage
for insert
to el_usage_writer
with check (true);

revoke all on table public.mcp_row_budget_policy from anon, authenticated, el_reader;
revoke all on table public.mcp_row_daily_budget from anon, authenticated, el_reader;
revoke all on table public.mcp_row_usage from anon, authenticated, el_reader;
revoke all on function public.apply_mcp_row_usage() from public;
