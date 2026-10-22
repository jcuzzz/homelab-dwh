create schema if not exists bronze;

create table if not exists bronze.load_log (
    load_id bigint generated always as identity primary key,
    source text not null,
    table_name text not null,
    source_file text not null,
    source_modified_at timestamptz not null,
    archived_file text not null,
    file_sha256 text not null,
    row_count integer not null default 0,
    loaded_at timestamptz not null default now()
);

create index if not exists load_log_table_latest_idx on bronze.load_log (table_name, load_id desc);
