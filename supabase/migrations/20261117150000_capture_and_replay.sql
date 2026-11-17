drop table private.watch_ecg_samples;
drop table private.watch_optical_beats;

alter table private.intervals drop column flagged;
alter table private.intervals
    add column flag smallint not null check (flag between 0 and 6);

alter table private.hrv_readings
    add column window_ms double precision not null,
    add column accepted_count integer not null;

drop index private.frame_samples_session_id;
drop index private.beats_session_id;
drop index private.intervals_session_id;
drop index private.hrv_readings_session_id;

alter table private.frame_samples add primary key (session_id, t_ms);
alter table private.beats add primary key (session_id, t_ms);
alter table private.intervals add primary key (session_id, t_ms);
alter table private.hrv_readings add primary key (session_id, t_ms);
