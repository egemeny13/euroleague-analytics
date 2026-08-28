-- Reverse of 0018_mcp_row_usage_writer_function.up.sql.
--
-- This restores migration 0016's direct-insert grant and policy, which is the
-- state the hosted server cannot actually use. Rolling back therefore means
-- rolling the server's code back with it.

grant insert on table public.mcp_row_usage to el_usage_writer;

create policy mcp_row_usage_writer_inserts_only
on public.mcp_row_usage
for insert
to el_usage_writer
with check (true);

drop function public.record_mcp_row_usage(uuid, text, date, text, integer);
