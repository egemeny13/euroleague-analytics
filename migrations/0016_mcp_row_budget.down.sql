-- migrations/0016_mcp_row_budget.down.sql
--
-- Removing the writer role disables hosted row-budget enforcement. Stop the
-- hosted server before applying this rollback.

drop trigger apply_mcp_row_usage_before_insert on public.mcp_row_usage;
drop function public.apply_mcp_row_usage();

drop table public.mcp_row_usage;
drop table public.mcp_row_daily_budget;
drop table public.mcp_row_budget_policy;

revoke usage on schema public from el_usage_writer;
revoke connect on database postgres from el_usage_writer;
drop role el_usage_writer;
