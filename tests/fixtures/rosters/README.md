# Roster fixture provenance

These fixtures are deterministic projections of measured, byte-preserved
season-wide responses. They retain every field consumed by the roster parser;
they are not presented as complete API bodies. The source array indices below
refer to the complete parent response before projection.

| Fixture | Parent endpoint | Parent body SHA-256 | Source indices | Fixture SHA-256 |
|---|---|---|---|---|
| `E2024.selected.json` | `/v2/competitions/E/seasons/E2024/people` | `8c296876c4fb3d11f83ab46520e6d16e37557bd7028c7b390440e64271b625b0` | 17, 24, 38 | `2f518166c3343a9542b3d9c7fb89d180a02c3c6ba4d1c456d1ae71ccc9cbc97c` |
| `E2025.selected.json` | `/v2/competitions/E/seasons/E2025/people` | `42efabd86e404a4956d729e9f36aec5c03416aa956a647c22458a9838290c460` | 0, 44, 87 | `677d961c3182996b41cd8bb30dad34a0de0bb8f569a4b0a7b6005ea608df7341` |
| `E2026.selected.json` | `/v2/competitions/E/seasons/E2026/people` | `6f5334f5f11b4e3f7cdbdbaba7ba2a33e88da224afdb276be1d61c3645b1edc9` | 0, 1, 202 | `a96cfedc19519c829b81c7ea6c2f1c239ee0f1459b387a00c903fd63b70a4cf2` |

Together the projections cover three seasons, six clubs, two staff role
codes, active and inactive registrations, null optional values, and both
three-character and zero-padded six-character person codes. The complete
E2024 Panathinaikos response remains committed separately as
`tests/fixtures/roster_people_pan_e2024.json`; its SHA-256 is
`2722f652b281e609c7b9665e527c0b7a1d86f269f0980a66c28cb7ebcabc5490`.
