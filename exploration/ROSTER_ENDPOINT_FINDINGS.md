# EuroLeague Roster Endpoint Reconnaissance Findings

Verdict: The public EuroLeague API exposes pre-season and seasonal rosters through the `/v2/competitions/{competitionCode}/seasons/{seasonCode}/people` and `/v2/competitions/{competitionCode}/seasons/{seasonCode}/clubs/{clubCode}/people` endpoints.

## Probed Endpoints Log

| URL | HTTP Status | Response Size (bytes) | Body SHA-256 |
|---|---|---|---|
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/people` | 200 | 596978 | 8c296876c4fb3d11f83ab46520e6d16e37557bd7028c7b390440e64271b625b0 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/clubs/PAN/people` | 200 | 58312 | 2722f652b281e609c7b9665e527c0b7a1d86f269f0980a66c28cb7ebcabc5490 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2025/people` | 200 | 590245 | 42efabd86e404a4956d729e9f36aec5c03416aa956a647c22458a9838290c460 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2025/clubs/PAN/people` | 200 | 55977 | 906342b387996e8330503a92c6d8759f854c5ace63a1618de54ed8c31b4a3928 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/people` | 200 | 223831 | 6f5334f5f11b4e3f7cdbdbaba7ba2a33e88da224afdb276be1d61c3645b1edc9 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/clubs/PAN/people` | 200 | 21288 | 4214cb97fa88f6577ab3a012015bc4645acacc4d89ed9866009865039368d860 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/clubs` | 200 | 12072 | dcf44a81eac7f4607e6d9f8635a1206b7a88fb750c318823bca1e9ed69c8747b |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/clubs/PAN` | 200 | 651 | e01e09f95d96cea5f4f91ef2eb1b8cd85d5923d7725daa4a096625910f6fed17 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/teams` | 404 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/rosters` | 404 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/players` | 404 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/athletes` | 404 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| `https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/squads` | 404 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| `https://api-live.euroleague.net/v2/competitions/E/clubs` | 404 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| `https://api-live.euroleague.net/v2/clubs` | 200 | 247624 | 357d182de86774cb31253d31b5dcf24e1b2d097c35b87592f8b0695de43aaa23 |
| `https://api-live.euroleague.net/v2/clubs/PAN` | 200 | 746 | 41362e377db6a0c10c8927d3e2cb7bfcdcc1b659e37a5e0fd74f0e13a43186a7 |
| `https://api-live.euroleague.net/v2/people` | 200 | 216050 | c37ff321ce6596d4b6f0673b4960795e5fb4f193bfd0d991a48b89fcf2de2fcf |
| `https://live.euroleague.net/api/Roster?seasoncode=E2024` | 200 | 975 | cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c |
| `https://live.euroleague.net/api/Roster?seasoncode=E2024&teamcode=PAN` | 200 | 975 | cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c |
| `https://live.euroleague.net/api/Players?seasoncode=E2024` | 200 | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| `https://live.euroleague.net/api/Teams?seasoncode=E2024` | 200 | 975 | cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c |
| `https://live.euroleague.net/api/ClubRoster?seasoncode=E2024&clubcode=PAN` | 200 | 975 | cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c |
| `https://live.euroleague.net/api/TeamRoster?seasoncode=E2024&teamcode=PAN` | 200 | 975 | cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c |

## Structural Analysis of the Endpoint

The valid roster endpoint is:
`GET https://api-live.euroleague.net/v2/competitions/{competitionCode}/seasons/{seasonCode}/clubs/{clubCode}/people`
(or season-wide at `GET https://api-live.euroleague.net/v2/competitions/{competitionCode}/seasons/{seasonCode}/people`)

### Key Schema Fields

Each entry represents a person registered with a club in that season:
- `person.code`: Opaque player/person identifier string (e.g. `"LHK"`, `"011867"`)
- `person.name`: Full display name (e.g. `"PLEISS, TIBOR"`)
- `person.passportName` / `person.passportSurname`: First and last names
- `person.birthDate`: ISO timestamp (e.g. `"1989-11-02T00:00:00"`)
- `person.height`: Integer height in cm (e.g. `218`)
- `person.weight`: Integer weight in kg (e.g. `113`)
- `person.country`: Object with `code` and `name`
- `type`: Role code (`"J"` for Player, `"Z"` for Staff/Score Crew, `"C"` for Coach)
- `typeName`: Role display name (`"Player"`, `"Head Coach"`, `"Assistant Coach"`)
- `dorsal`: Jersey number string (e.g. `"24"`)
- `position`: Numeric position identifier
- `positionName`: Position name (`"Guard"`, `"Forward"`, `"Center"`)
- `club.code`: Club identifier string (e.g. `"PAN"`)
- `season.code`: Season identifier string (e.g. `"E2024"`, `"E2026"`)
- `active`: Boolean indicating registration status

### Pre-season Finding (E2026)

Probing `https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/people` on 2026-08-23 yielded **204 registered individuals** (players and staff) across participating clubs for the upcoming 2026-27 season well before opening tip-off (2026-09-24). Roster data IS available before game 1.
