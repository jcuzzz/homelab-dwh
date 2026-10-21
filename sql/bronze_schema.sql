CREATE schema if NOT EXISTS bronze;

create table if not exists bronze.load_log (
  load_id bigint generated always as identity primary key,
  source text not null,
  table_name text not null,
  source_file text not null,
  source_modified_at timestamptz not null,
  row_count integer not null default 0,
  loaded_at timestamptz not null default now()
);
