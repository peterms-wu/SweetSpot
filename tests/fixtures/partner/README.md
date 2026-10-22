# Official seasonal sales page (test copies)

Trimmed copies of `https://partner.steamgames.com/doc/marketing/discounts/seasonalsales` for feature 012's parser tests.
Only the documentation body is kept; each file names its source in the first line.

| File | Source | Shows |
|---|---|---|
| `seasonalsales-2026-09-27.html` | the official page, fetched 2026-09-27 | 4 sales, day-first dates (`1 October, 2026 - 8 October, 2026`) |
| `seasonalsales-2025-05-17.html` | Wayback snapshot 20250517002119 | month-first dates (`June 26, 2025 - July 10, 2025`) and `TBD` |
| `seasonalsales-2024-03-20.html` | Wayback snapshot 20240320171123 | year written once (`March 14 - March 21, 2024`) |

The feature itself only reads the official page; archive.org was used during planning to check the format history (research R0.2).
