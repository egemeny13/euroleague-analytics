-- 0015 roster biography - source-native player biography fields.

alter table roster_registration
    add column birth_date date,
    add column passport_name text,
    add column passport_surname text,
    add constraint roster_registration_passport_name_trimmed
        check (
            passport_name is null
            or (passport_name = btrim(passport_name) and passport_name <> '')
        ),
    add constraint roster_registration_passport_surname_trimmed
        check (
            passport_surname is null
            or (passport_surname = btrim(passport_surname) and passport_surname <> '')
        );
