create schema private;

create table private.sessions (
    id bigint generated always as identity primary key,
    started_wall_ns bigint not null,
    started_monotonic_ns bigint not null
);

create table private.frame_samples (
    session_id bigint not null references private.sessions (id) on delete cascade,
    t_ms bigint not null,
    forehead_r double precision not null,
    forehead_g double precision not null,
    forehead_b double precision not null,
    left_cheek_r double precision not null,
    left_cheek_g double precision not null,
    left_cheek_b double precision not null,
    right_cheek_r double precision not null,
    right_cheek_g double precision not null,
    right_cheek_b double precision not null,
    moving boolean not null
);

create table private.beats (
    session_id bigint not null references private.sessions (id) on delete cascade,
    t_ms bigint not null
);

create table private.intervals (
    session_id bigint not null references private.sessions (id) on delete cascade,
    t_ms bigint not null,
    interval_ms double precision not null,
    flagged boolean not null
);

create table private.hrv_readings (
    session_id bigint not null references private.sessions (id) on delete cascade,
    t_ms bigint not null,
    rmssd_ms double precision not null,
    sdnn_ms double precision not null
);

create table private.watch_ecg_samples (
    session_id bigint not null references private.sessions (id) on delete cascade,
    recording integer not null,
    sample_index integer not null,
    microvolts double precision not null
);

create table private.watch_optical_beats (
    session_id bigint not null references private.sessions (id) on delete cascade,
    t_ms bigint not null
);

create index frame_samples_session_id on private.frame_samples (session_id);
create index beats_session_id on private.beats (session_id);
create index intervals_session_id on private.intervals (session_id);
create index hrv_readings_session_id on private.hrv_readings (session_id);
create index watch_ecg_samples_session_id on private.watch_ecg_samples (session_id);
create index watch_optical_beats_session_id on private.watch_optical_beats (session_id);

alter table private.sessions enable row level security;
alter table private.frame_samples enable row level security;
alter table private.beats enable row level security;
alter table private.intervals enable row level security;
alter table private.hrv_readings enable row level security;
alter table private.watch_ecg_samples enable row level security;
alter table private.watch_optical_beats enable row level security;

revoke all on schema private from public;
revoke all on all tables in schema private from public;
revoke all on all sequences in schema private from public;
