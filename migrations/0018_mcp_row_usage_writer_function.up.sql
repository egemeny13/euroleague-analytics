-- migrations/0018_mcp_row_usage_writer_function.up.sql
--
-- REPAIR. Migration 0016 granted el_usage_writer `insert` on mcp_row_usage and
-- nothing else, and src/euroleague/mcp/row_budget.py writes with
-- `insert ... returning daily_row_limit, remaining_rows`. PostgreSQL requires
-- SELECT privilege on every column a RETURNING clause returns, so every hosted
-- tool call failed with:
--
--     permission denied for table mcp_row_usage
--
-- Measured against production on 2026-08-28 as el_usage_writer: the same insert
-- succeeds without the RETURNING clause and is refused with it.
--
-- WHY NOT JUST GRANT SELECT ON THE TWO COLUMNS. Because RLS is enabled on the
-- table, and a RETURNING clause also applies SELECT policies. Making it work
-- would need a SELECT policy, and no policy can be scoped to "only the row this
-- statement just wrote" - it would let the writer read every subject's usage
-- history. That is the opposite of what the role is for.
--
-- WHAT THIS DOES INSTEAD. One security-definer function performs the insert and
-- returns the two integers the caller needs. The writer is then granted EXECUTE
-- on that function and its table privilege is removed entirely, so this repair
-- leaves the role with STRICTLY LESS privilege than migration 0016 gave it: it
-- can no longer write the table directly, and it still cannot read it. The
-- BEFORE INSERT trigger continues to compute and enforce the budget.

create function public.record_mcp_row_usage(
    p_operation_id uuid,
    p_subject text,
    p_usage_date date,
    p_operation text,
    p_row_delta integer
)
returns table (daily_limit integer, remaining integer)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    return query
    with recorded as (
        insert into public.mcp_row_usage
            (operation_id, subject, usage_date, operation, row_delta)
        values (p_operation_id, p_subject, p_usage_date, p_operation, p_row_delta)
        returning mcp_row_usage.daily_row_limit, mcp_row_usage.remaining_rows
    )
    select recorded.daily_row_limit, recorded.remaining_rows from recorded;
end;
$$;

comment on function public.record_mcp_row_usage(uuid, text, date, text, integer) is
    'The only write path into mcp_row_usage. Security definer so the caller needs no privilege on the table itself, and returns only the two integers the budget discloses.';

revoke all on function public.record_mcp_row_usage(uuid, text, date, text, integer) from public;
grant execute on function public.record_mcp_row_usage(uuid, text, date, text, integer)
    to el_usage_writer;

-- The direct write path is withdrawn now that the function replaces it.
drop policy mcp_row_usage_writer_inserts_only on public.mcp_row_usage;
revoke insert on table public.mcp_row_usage from el_usage_writer;
