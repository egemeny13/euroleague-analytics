-- Reverse of 0015_roster_biography.up.sql.

alter table roster_registration
    drop column birth_date,
    drop column passport_name,
    drop column passport_surname;
