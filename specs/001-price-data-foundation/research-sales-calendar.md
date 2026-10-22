# Steam major sales calendar, 2019 to 2027

Compiled 2026-09-24. Primary sources are Valve's own posts: Steam News (app 593110), Steamworks Development group announcements, the Steam Promotions group, and the Steamworks "Upcoming Events" / "Seasonal Sales" docs. I read post text from Valve's public event JSON (store.steampowered.com/events/ajaxgetpartnereventspageable) and the ISteamNews API. I did not scrape steamdb.info.

**How to read the dates**
- `start_date` is the day the sale **opens at 10:00 Pacific**. `end_date` is the day it **closes at 10:00 Pacific**, so the last full day of discounts is `end_date - 1`.
- "Pacific" means PST (UTC-8) from about November to March and PDT (UTC-7) from about March to November. Valve sometimes writes "PST" for summer dates, for example "July 8th, 2021 at 10AM PST". The real offset in summer is still PDT (UTC-7).
- Confidence levels:
  - `official`: both dates are stated by Valve.
  - `secondary`: one date comes from reputable press or a community source.
  - `unverified`: not confirmed.

## Table 1: Seasonal sales and Halloween / Steam Scream

| year | name (English) | 中文名稱 | start_date | end_date | time_note | source_url | confidence |
|---|---|---|---|---|---|---|---|
| 2019 | Lunar New Year Sale | 農曆新年特賣 | 2019-02-04 | 2019-02-11 | 10:00 PT assumed. Valve's post confirms the start date. The end date comes from PC Gamer. | https://steamcommunity.com/games/593110/announcements/detail/1750114346364440017 ; https://www.pcgamer.com/the-steam-lunar-new-year-sale-2019-is-live-now/ | secondary |
| 2019 | Summer Sale (Steam Grand Prix) | 夏季特賣 | 2019-06-25 | 2019-07-09 | The post says "For the next 14 days", so the end date is start + 14 days. The Grand Prix mini-event ended earlier, on 07-07 at 10:00 PDT. | https://steamcommunity.com/games/593110/announcements/detail/1616144864293404894 | official |
| 2019 | Halloween Sale | 萬聖節特賣 | 2019-10-28 | 2019-11-01 | Valve: "until November 1st at 10am Pacific". The start date comes from press (gg.deals). | https://steamcommunity.com/games/593110/announcements/detail/1666821776717777071 ; https://gg.deals/gaming-news/dates-of-steam-halloween-sale-steam-autumn-sale-nad-steam-winter-sale/ | secondary |
| 2019 | Autumn Sale | 秋季特賣 | 2019-11-26 | 2019-12-03 | "Offers end Tuesday December 3rd at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/3605623508392801946 | official |
| 2019 | Winter Sale | 冬季特賣 | 2019-12-19 | 2020-01-02 | "Discounts end January 2nd at 10am PST" | https://steamcommunity.com/games/593110/announcements/detail/3180035790689045584 | official |
| 2020 | Lunar New Year Sale | 農曆新年特賣 | 2020-01-23 | 2020-01-27 | "now through January 27th at 10 am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/1706236518822639430 | official |
| 2020 | Summer Sale | 夏季特賣 | 2020-06-25 | 2020-07-09 | Valve's post confirms the start and says "the next two weeks". The end date (07-09, 10:00 PDT) comes from press. | https://steamcommunity.com/games/593110/announcements/detail/2445966074571282888 ; https://www.gamespot.com/gallery/steam-summer-sale-2020-ends-soon-best-deals-to-gra/2900-3511/ | secondary |
| 2020 | Halloween Sale | 萬聖節特賣 | 2020-10-29 | 2020-11-02 | "on now until November 2nd at 10am Pacific". The start date is the post date. | https://steamcommunity.com/games/593110/announcements/detail/2922233151838517106 | official |
| 2020 | Autumn Sale | 秋季特賣 | 2020-11-25 | 2020-12-01 | "ending at 10am Pacific on Tuesday, December 1st" | https://steamcommunity.com/games/593110/announcements/detail/2914353120901701711 | official |
| 2020 | Winter Sale | 冬季特賣 | 2020-12-22 | 2021-01-05 | Valve's post confirms the start. The end (01-05 18:00 UTC = 10:00 PST) comes from the end time on Valve's Steam Promotions "Winter Sale –" sub-events in the Steam events JSON. Press agrees. | https://steamcommunity.com/games/593110/announcements/detail/2904223191309839604 ; https://tagn.wordpress.com/2021/01/05/the-end-of-the-steam-winter-sale-with-2020-stats-and-awards/ | official |
| 2021 | Lunar New Year Sale | 農曆新年特賣 | 2021-02-11 | 2021-02-15 | "now through February 15th at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/3016818255535621678 | official |
| 2021 | Summer Sale | 夏季特賣 | 2021-06-24 | 2021-07-08 | "From June 24th to July 8th". Ends "July 8th, 2021 at 10AM PST" (really PDT). | https://steamcommunity.com/games/593110/announcements/detail/2981927408950091621 | official |
| 2021 | Halloween Sale | 萬聖節特賣 | 2021-10-28 | 2021-11-01 | "runs until November 1st at 10am Pacific". The start date is the post date. | https://steamcommunity.com/games/593110/announcements/detail/3021345332649804118 | official |
| 2021 | Autumn Sale | 秋季特賣 | 2021-11-24 | 2021-12-01 | "now through 10am Pacific on Wednesday, December 1st" | https://steamcommunity.com/games/593110/announcements/detail/4555948886325351153 | official |
| 2021 | Winter Sale | 冬季特賣 | 2021-12-22 | 2022-01-05 | "through January 5th at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/5071614219293722782 | official |
| 2022 | Lunar New Year Sale (last one) | 農曆新年特賣 | 2022-01-27 | 2022-02-03 | "now through February 3rd at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/3100165379962854007 | official |
| 2022 | Summer Sale | 夏季特賣 | 2022-06-23 | 2022-07-07 | Valve: "until July 7th (at 10am PT)". Valve's post is dated 06-24. The 06-23 10:00 PT start comes from press. | https://steamcommunity.com/games/593110/announcements/detail/3335493590017083918 ; https://gamingbolt.com/steams-summer-sale-2022-set-to-kick-off-on-june-23 | secondary |
| 2022 | Steam Scream Fest (Halloween) | Steam 尖叫節(萬聖節) | 2022-10-25 | 2022-11-01 | "October 25, 10:00 AM PDT (GMT-7) to November 1, 10:00 AM PDT" | https://steamcommunity.com/groups/steamworks/announcements/detail/3404177923749444204 | official |
| 2022 | Autumn Sale | 秋季特賣 | 2022-11-22 | 2022-11-29 | "November 22nd at 10am PST (UTC -8) until November 29th at 10am PST" | https://steamcommunity.com/games/593110/announcements/detail/3388424091280374210 | official |
| 2022 | Winter Sale | 冬季特賣 | 2022-12-22 | 2023-01-05 | "December 22nd at 10am PST through January 5, 2023 at 10am PST" | https://steamcommunity.com/games/593110/announcements/detail/3653012651448289509 | official |
| 2023 | Spring Sale (first; replaced LNY) | 春季特賣 | 2023-03-16 | 2023-03-23 | "March 16th - March 23rd at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/3694679839286985809 | official |
| 2023 | Summer Sale | 夏季特賣 | 2023-06-29 | 2023-07-13 | "runs until July 13th at 10am PT" | https://steamcommunity.com/groups/steamworks/announcements/detail/3645136358931000681 ; https://steamcommunity.com/games/593110/announcements/detail/3682303734604033315 | official |
| 2023 | Steam Scream: The Revenge | Steam 尖叫節 2 | 2023-10-26 | 2023-11-02 | "October 26 at 10:00 AM PDT (UTC-7) to November 2 at 10:00 AM PDT" | https://steamcommunity.com/groups/steamworks/announcements/detail/3719453992471603363 | official |
| 2023 | Autumn Sale | 秋季特賣 | 2023-11-21 | 2023-11-28 | "November 21st at 10am PST (UTC -8) and November 28th at 10am PST" | https://steamcommunity.com/games/593110/announcements/detail/3823053915973575702 | official |
| 2023 | Winter Sale | 冬季特賣 | 2023-12-21 | 2024-01-04 | "December 21st at 10am PST until January 4th at 10am PST" | https://steamcommunity.com/games/593110/announcements/detail/3823053915973576612 | official |
| 2024 | Spring Sale | 春季特賣 | 2024-03-14 | 2024-03-21 | "March 14th through 21st at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/4118050466868346371 | official |
| 2024 | Summer Sale | 夏季特賣 | 2024-06-27 | 2024-07-11 | 10:00 PT convention. The schedule says "June 27 - July 11". | https://steamcommunity.com/groups/steamworks/announcements/detail/3970553774441642999 | official |
| 2024 | Steam Scream Fest 3 | Steam 尖叫節 3 | 2024-10-28 | 2024-11-04 | 10:00 PT convention. The schedule says "October 28 - November 4". | https://steamcommunity.com/groups/steamworks/announcements/detail/3970553774441642999 | official |
| 2024 | Autumn Sale | 秋季特賣 | 2024-11-27 | 2024-12-04 | "now through December 4th at 10am PST" | https://steamcommunity.com/games/593110/announcements/detail/4464851103138185583 | official |
| 2024 | Winter Sale | 冬季特賣 | 2024-12-19 | 2025-01-02 | "runs through January 2 (2025!) at 10am PST" | https://steamcommunity.com/games/593110/announcements/detail/520825178851115845 | official |
| 2025 | Spring Sale | 春季特賣 | 2025-03-13 | 2025-03-20 | "on now through March 20th at 10am PT" | https://steamcommunity.com/games/593110/announcements/detail/520833241446351892 | official |
| 2025 | Summer Sale | 夏季特賣 | 2025-06-26 | 2025-07-10 | "until July 10th at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/500577186633220419 | official |
| 2025 | Autumn Sale (moved from late Nov to late Sep) | 秋季特賣 | 2025-09-29 | 2025-10-06 | "through October 6th at 10 a.m. PT" | https://steamcommunity.com/games/593110/announcements/detail/507340830949770005 ; https://steamcommunity.com/groups/steamworks/announcements/detail/532104542613932038 | official |
| 2025 | Steam Scream 4 | Steam 尖叫節 4 | 2025-10-27 | 2025-11-03 | 10:00 PT convention. The schedule says "October 27 – November 3". | https://steamcommunity.com/groups/steamworks/announcements/detail/497187349280587904 | official |
| 2025 | Winter Sale | 冬季特賣 | 2025-12-18 | 2026-01-05 | 10:00 PT convention. "December 18th 2025 through January 5th 2026" (18 days). | https://steamcommunity.com/games/593110/announcements/detail/492711197218440448 | official |
| 2026 | Spring Sale | 春季特賣 | 2026-03-19 | 2026-03-26 | "on now through March 26th at 10 a.m. PT" | https://steamcommunity.com/games/593110/announcements/detail/526496349181445006 | official |
| 2026 | Summer Sale | 夏季特賣 | 2026-06-25 | 2026-07-09 | "Now through July 9th at 10 a.m. Pacific" | https://steamcommunity.com/games/593110/announcements/detail/673998115585395513 | official |
| 2026 | Autumn Sale (upcoming) | 秋季特賣 | 2026-10-01 | 2026-10-08 | 10:00 PT convention. Announced in advance. | https://partner.steamgames.com/doc/marketing/upcoming_events ; https://steamcommunity.com/groups/steamworks/announcements/detail/668369251018480125 | official |
| 2026 | Steam Scream V Fest (upcoming) | Steam 尖叫節 5 | 2026-10-26 | 2026-11-02 | 10:00 PT convention. Announced in advance. | https://steamcommunity.com/groups/steamworks/announcements/detail/668369251018480125 | official |
| 2026 | Winter Sale (upcoming) | 冬季特賣 | 2026-12-17 | 2027-01-04 | 10:00 PT convention. Announced in advance (18 days). | https://partner.steamgames.com/doc/marketing/discounts/seasonalsales ; https://steamcommunity.com/groups/steamworks/announcements/detail/668369251018480125 | official |
| 2027 | Spring Sale (announced) | 春季特賣 | 2027-03-18 | 2027-03-25 | 10:00 PT convention. Announced in advance. | https://partner.steamgames.com/doc/marketing/discounts/seasonalsales ; https://steamcommunity.com/groups/steamworks/announcements/detail/668369251018480125 | official |
| 2027 | Summer Sale (announced) | 夏季特賣 | 2027-06-24 | 2027-07-08 | 10:00 PT convention. Announced in advance. | https://partner.steamgames.com/doc/marketing/discounts/seasonalsales ; https://steamcommunity.com/groups/steamworks/announcements/detail/668369251018480125 | official |
| 2027 | Autumn Sale | 秋季特賣 | not announced | not announced | Estimate: late Sep to early Oct 2027, 7 days (see patterns) | (none) | unverified |
| 2027 | Winter Sale | 冬季特賣 | not announced | not announced | Estimate: about Dec 16 to 23, 2027, for 14 to 18 days, ending in early Jan 2028 | (none) | unverified |

**Years with no sale in a slot**
- 2019 to 2022 had no Spring Sale. The Lunar New Year Sale filled that seasonal slot.
- From 2023 on there is no Lunar New Year Sale. Valve's 2022-09-27 post announced the change: https://steamcommunity.com/groups/steamworks/announcements/detail/3282583269823858401

## Table 2: Other Valve-run themed sales / fests with store-wide themed discounts (Next Fest excluded)

Unless stated otherwise:
- Times follow the 10:00 PT open/close convention. Many fest posts state it explicitly, for example Survival Fest: "August 1, 10:00 AM PDT (GMT-7) to August 8, 10:00 AM PDT".
- A fest covers only games that match its theme and opted in, so discounts are narrower than in a seasonal sale.
- Chinese names are descriptive translations, not verified Steam zh-TW localized titles.
- Source codes used in the table:
  - SW23 = https://steamcommunity.com/groups/steamworks/announcements/detail/3645136358931000681
  - SW24 = https://steamcommunity.com/groups/steamworks/announcements/detail/3970553774441642999
  - SW25H1 = https://steamcommunity.com/groups/steamworks/announcements/detail/4264427597939246984
  - SW25H2 = https://steamcommunity.com/groups/steamworks/announcements/detail/497187349280587904
  - SW26H2 = https://steamcommunity.com/groups/steamworks/announcements/detail/493837645658461608 (repeats the first half of 2026 too)
  - SW27 = https://steamcommunity.com/groups/steamworks/announcements/detail/668369251018480125

| year | name (English) | 中文名稱 | start_date | end_date | time_note | source_url | confidence |
|---|---|---|---|---|---|---|---|
| 2019 | Remote Play Together Sale & Event | 遠端同樂特賣 | 2019-11-20 | 2019-11-25 | "through November 25th at 10AM" | https://steamcommunity.com/games/593110/announcements/detail/3605623508387016471 | official |
| 2020 | Digital Tabletop Fest | 數位桌遊節 | 2020-10-21 | 2020-10-26 | Starts 10:00 PT | https://steamcommunity.com/games/593110/announcements/detail/2769108226045128183 | official |
| 2020 | Fighting Game Sale | 格鬥遊戲特賣 | 2020-11-12 | 2020-11-16 | "until November 16th at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/2897465256256630851 | official |
| 2021 | Remote Play Together Sale | 遠端同樂特賣 | 2021-03-25 | 2021-03-29 | "March 25th - 29th at 10am Pacific" | https://steamcommunity.com/groups/steamworks/announcements/detail/3061855517879784503 | official |
| 2021 | Golden Week Sale | 黃金週特賣 | 2021-04-29 | 2021-05-06 | 10:00 PT | https://store.steampowered.com/news/group/39049601/view/3013444995204328631 | official |
| 2021 | Open World Sale | 開放世界特賣 | 2021-05-27 | 2021-05-31 | "May 27 - 31, 10am Pacific" | https://steamcommunity.com/groups/steamworks/announcements/detail/3119280855634041742 | official |
| 2021 | Digital Tabletop Fest (RPG Edition) | 數位桌遊節 | 2021-10-21 | 2021-10-25 | "through the 25th at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/2858087379437902206 | official |
| 2022 | Remote Play Together Sale | 遠端同樂特賣 | 2022-02-28 | 2022-03-07 | "through Monday March 7th at 10am Pacific" | https://steamcommunity.com/games/593110/announcements/detail/3091161894501379845 | official |
| 2022 | JRPG Sale | 日式 RPG 特賣 | 2022-03-14 | 2022-03-21 | Starts 10:00 PT | https://steamcommunity.com/games/593110/announcements/detail/3091163163109910645 | official |
| 2022 | Simfest: Hobby Edition | 模擬遊戲節:嗜好版 | 2022-03-28 | 2022-04-04 | "March 28 at 10am Pacific - April 4th at 10am Pacific" | https://steamcommunity.com/groups/steamworks/announcements/detail/3133947359568029623 | official |
| 2022 | Racing Fest | 賽車節 | 2022-05-23 | 2022-05-30 | 10:00 PT | https://steamcommunity.com/games/593110/announcements/detail/3180116240852632901 | official |
| 2022 | VR Fest | VR 節 | 2022-07-18 | 2022-07-25 | "10:00 AM PDT (GMT-7)" | https://steamcommunity.com/groups/steamworks/announcements/detail/3218394291609115018 | official |
| 2022 | Survival Fest | 生存遊戲節 | 2022-08-01 | 2022-08-08 | "10:00 AM PDT (GMT-7)" | https://steamcommunity.com/groups/steamworks/announcements/detail/3222900587040657570 | official |
| 2022 | Steam Bash Bash (fighting/brawler) | 格鬥亂鬥節 | 2022-09-19 | 2022-09-26 | "10:00 AM PDT (GMT-7)" | https://steamcommunity.com/groups/steamworks/announcements/detail/3330988721845691321 | official |
| 2023 | Base Builder Fest | 基地建造節 | 2023-01-23 | 2023-01-30 | "10:00 AM PST (UTC-8)" | https://steamcommunity.com/groups/steamworks/announcements/detail/3225161106686509392 | official |
| 2023 | Mystery Fest | 推理解謎節 | 2023-02-20 | 2023-02-27 | "10:00 AM PST (UTC-8)" | https://steamcommunity.com/groups/steamworks/announcements/detail/3524658636207210572 | official |
| 2023 | Puzzle Fest | 益智解謎節 | 2023-04-24 | 2023-05-01 | "10:00 AM PDT (UTC-7)" | https://steamcommunity.com/groups/steamworks/announcements/detail/3611354355084733654 | official |
| 2023 | Sports Fest | 運動遊戲節 | 2023-05-15 | 2023-05-22 | "10:00 AM PDT (UTC-7)" | https://steamcommunity.com/groups/steamworks/announcements/detail/3611354355085197083 | official |
| 2023 | Stealth Fest | 潛行遊戲節 | 2023-07-24 | 2023-07-31 | 10:00 PT convention | SW23 | official |
| 2023 | Visual Novel Fest | 視覺小說節 | 2023-08-07 | 2023-08-14 | 10:00 PT convention | SW23 | official |
| 2023 | Strategy Fest | 策略遊戲節 | 2023-08-28 | 2023-09-04 | 10:00 PT convention | SW23 | official |
| 2023 | SHMUP Fest | 射擊遊戲 (STG) 節 | 2023-09-25 | 2023-10-02 | 10:00 PT convention | SW23 | official |
| 2023 | VR Fest | VR 節 | 2023-12-04 | 2023-12-11 | "10:00 AM PST (GMT-8)" | https://steamcommunity.com/groups/steamworks/announcements/detail/6690718524057147206 | official |
| 2024 | Capitalism and Economy Fest | 資本主義與經濟節 | 2024-01-08 | 2024-01-15 | 10:00 PT convention | SW24 | official |
| 2024 | Pirates vs. Ninjas Fest | 海盜對忍者節 | 2024-01-22 | 2024-01-29 | 10:00 PT convention | SW24 | official |
| 2024 | Remote Play Together Fest | 遠端同樂節 | 2024-02-12 | 2024-02-19 | 10:00 PT convention | SW24 | official |
| 2024 | Dinos vs. Robots Fest | 恐龍對機器人節 | 2024-02-26 | 2024-03-04 | 10:00 PT convention | SW24 | official |
| 2024 | Deckbuilders Fest | 牌組構築節 | 2024-03-25 | 2024-04-01 | 10:00 PT convention | SW24 | official |
| 2024 | FPS Fest | 第一人稱射擊節 | 2024-04-15 | 2024-04-22 | 10:00 PT convention | SW24 | official |
| 2024 | Farming Fest | 農場遊戲節 | 2024-04-29 | 2024-05-06 | 10:00 PT convention | SW24 | official |
| 2024 | Endless Replayability Fest | 無限重玩節 | 2024-05-13 | 2024-05-20 | 10:00 PT convention | SW24 | official |
| 2024 | Open World Survival Crafting Fest | 開放世界生存製作節 | 2024-05-27 | 2024-06-03 | 10:00 PT convention | SW24 | official |
| 2024 | Fighting Games Fest | 格鬥遊戲節 | 2024-07-15 | 2024-07-22 | Moved from the scheduled Aug 5–12. Valve's live post says "on now through July 22nd". | https://steamcommunity.com/games/593110/announcements/detail/4225021101233444836 | official |
| 2024 | Tower Defense Fest | 塔防遊戲節 | 2024-07-29 | 2024-08-05 | "August 5th at 10am Pacific" | SW24 | official |
| 2024 | Rhythm Fest | 節奏遊戲節 | 2024-08-19 | 2024-08-26 | "August 26th at 10am PT" | SW24 | official |
| 2024 | Space Exploration Fest | 太空探索節 | 2024-09-02 | 2024-09-09 | 10:00 PT convention | SW24 | official |
| 2024 | Planes, Trains, and Automobiles Fest | 飛機、火車與汽車節 | 2024-09-16 | 2024-09-23 | 10:00 PT convention | SW24 | official |
| 2024 | Turn-based RPG Fest | 回合制 RPG 節 | 2024-09-30 | 2024-10-07 | 10:00 PT convention | SW24 | official |
| 2024 | Cooking Fest | 烹飪遊戲節 | 2024-11-11 | 2024-11-18 | 10:00 PT convention | SW24 | official |
| 2025 | Real-Time Strategy Fest | 即時戰略節 | 2025-01-20 | 2025-01-27 | 10:00 PT convention | SW25H1 | official |
| 2025 | Idler Fest | 放置遊戲節 | 2025-02-03 | 2025-02-10 | 10:00 PT convention | SW25H1 | official |
| 2025 | Couch Co-Op Fest | 同樂合作節 | 2025-02-10 | 2025-02-17 | 10:00 PT convention | SW25H1 | official |
| 2025 | Visual Novel Fest | 視覺小說節 | 2025-03-03 | 2025-03-10 | 10:00 PT convention | SW25H1 | official |
| 2025 | City Builder & Colony Sim Fest | 城市建造與殖民模擬節 | 2025-03-24 | 2025-03-31 | 10:00 PT convention | SW25H1 | official |
| 2025 | Sokoban (Box-Pushing) Fest | 推箱子節 | 2025-04-21 | 2025-04-28 | 10:00 PT convention | SW25H1 | official |
| 2025 | Wargames Fest | 兵棋遊戲節 | 2025-04-28 | 2025-05-05 | 10:00 PT convention | SW25H1 | official |
| 2025 | Creature Collector Fest | 生物收集節 | 2025-05-12 | 2025-05-19 | 10:00 PT convention | SW25H1 | official |
| 2025 | Zombies vs. Vampires Fest | 殭屍對吸血鬼節 | 2025-05-26 | 2025-06-02 | 10:00 PT convention | SW25H1 | official |
| 2025 | Fishing Fest | 釣魚遊戲節 | 2025-06-16 | 2025-06-23 | 10:00 PT convention | SW25H1 | official |
| 2025 | Automation Fest | 自動化遊戲節 | 2025-07-14 | 2025-07-21 | "through July 21st at 10am Pacific". Valve's live post is dated 07-16. | SW25H2 | official |
| 2025 | Racing Fest | 賽車節 | 2025-07-28 | 2025-08-04 | 10:00 PT convention | SW25H2 | official |
| 2025 | 4X Fest | 4X 策略節 | 2025-08-11 | 2025-08-18 | 10:00 PT convention | SW25H2 | official |
| 2025 | Third Person Shooter Fest | 第三人稱射擊節 | 2025-08-25 | 2025-09-01 | 10:00 PT convention | SW25H2 | official |
| 2025 | Political Sim Fest | 政治模擬節 | 2025-09-08 | 2025-09-15 | 10:00 PT convention. It ran as scheduled (Steam Promotions post). | SW25H2 ; https://store.steampowered.com/news/group/39049601/view/507338927350220424 | official |
| 2025 | Animal Fest | 動物遊戲節 | 2025-11-10 | 2025-11-17 | 10:00 PT convention | SW25H2 | official |
| 2025 | Black Friday Special Offers (not a Steam sale event) | 黑色星期五特惠專區 | 2025-11-24 | 2025-12-01 | Valve set up a themed Special Offers hub. Seasonal-sale cooldown exemptions do NOT apply. | https://steamcommunity.com/groups/steamworks/announcements/detail/532104542613932038 | official |
| 2025 | Sports Fest | 運動遊戲節 | 2025-12-08 | 2025-12-15 | 10:00 PT convention | SW25H2 | official |
| 2026 | Detective Fest | 偵探遊戲節 | 2026-01-12 | 2026-01-19 | 10:00 PT convention | SW26H2 | official |
| 2026 | Board Game Fest | 桌上遊戲節 | 2026-01-26 | 2026-02-02 | 10:00 PT convention | SW26H2 | official |
| 2026 | Typing Fest (Spotlight) | 打字遊戲節 | 2026-02-05 | 2026-02-09 | 10:00 PT convention. Spotlight fests are shorter. | SW26H2 | official |
| 2026 | PvP Fest | PvP 對戰節 | 2026-02-09 | 2026-02-16 | 10:00 PT convention | SW26H2 | official |
| 2026 | Horse Fest (Spotlight) | 馬匹遊戲節 | 2026-02-19 | 2026-02-23 | 10:00 PT convention | SW26H2 | official |
| 2026 | Tower Defense Fest | 塔防遊戲節 | 2026-03-09 | 2026-03-16 | "through March 16th at 10 a.m. Pacific" | SW26H2 | official |
| 2026 | House & Home Fest | 居家遊戲節 | 2026-03-30 | 2026-04-06 | 10:00 PT convention | SW26H2 | official |
| 2026 | Hidden Object Fest (Spotlight) | 尋物遊戲節 | 2026-04-09 | 2026-04-13 | 10:00 PT convention | SW26H2 | official |
| 2026 | Medieval Fest | 中世紀遊戲節 | 2026-04-20 | 2026-04-27 | 10:00 PT convention | SW26H2 | official |
| 2026 | Deckbuilders Fest | 牌組構築節 | 2026-05-04 | 2026-05-11 | 10:00 PT convention | SW26H2 | official |
| 2026 | Ocean Fest | 海洋遊戲節 | 2026-05-18 | 2026-05-25 | 10:00 PT convention | SW26H2 | official |
| 2026 | Bullet Fest | 彈幕/子彈遊戲節 | 2026-06-08 | 2026-06-15 | 10:00 PT convention | SW26H2 | official |
| 2026 | Social Deduction Fest | 社交推理節 | 2026-07-13 | 2026-07-16 | 10:00 PT convention | SW26H2 | official |
| 2026 | Train Fest | 火車遊戲節 | 2026-07-20 | 2026-07-27 | 10:00 PT convention | SW27 | official |
| 2026 | Cyberpunk Fest | 賽博龐克節 | 2026-08-03 | 2026-08-10 | 10:00 PT convention | SW27 | official |
| 2026 | Pins & Pegs Fest | 彈珠與釘板節 | 2026-08-17 | 2026-08-20 | 10:00 PT convention | SW27 | official |
| 2026 | PvE Survival Crafting Fest | PvE 生存製作節 | 2026-08-31 | 2026-09-07 | 10:00 PT convention | SW27 | official |
| 2026 | Programming Fest | 程式設計遊戲節 | 2026-09-10 | 2026-09-14 | 10:00 PT convention | SW27 | official |
| 2026 | Party-Based RPG Fest | 小隊 RPG 節 | 2026-09-14 | 2026-09-21 | 10:00 PT convention | SW27 | official |
| 2026 | Cooking Fest | 烹飪遊戲節 | 2026-10-12 | 2026-10-19 | 10:00 PT convention | SW27 | official |
| 2026 | Auto-Battler RPG Fest | 自走棋 RPG 節 | 2026-11-16 | 2026-11-23 | 10:00 PT convention | SW27 | official |
| 2026 | Black Friday Special Offers hub | 黑色星期五特惠專區 | TBD | TBD | Valve says "Specific dates and details to come". 2025 used Nov 24 to Dec 1. | SW27 | unverified |
| 2027 | Desktop Companion Fest | 桌面陪伴節 | 2027-01-14 | 2027-01-18 | 10:00 PT convention | SW27 | official |
| 2027 | Shop Keeper Fest | 經營商店節 | 2027-01-25 | 2027-02-01 | 10:00 PT convention | SW27 | official |
| 2027 | Sheep Fest | 綿羊節 | 2027-02-04 | 2027-02-08 | 10:00 PT convention | SW27 | official |
| 2027 | Couch Co-Op Fest | 同樂合作節 | 2027-02-08 | 2027-02-15 | 10:00 PT convention | SW27 | official |
| 2027 | Rhythm Fest | 節奏遊戲節 | 2027-03-08 | 2027-03-15 | 10:00 PT convention | SW27 | official |
| 2027 | Dinos vs. Robots Fest | 恐龍對機器人節 | 2027-03-29 | 2027-04-05 | 10:00 PT convention | SW27 | official |
| 2027 | Racing Fest | 賽車節 | 2027-04-12 | 2027-04-19 | 10:00 PT convention | SW27 | official |
| 2027 | Witch Fest | 女巫節 | 2027-04-22 | 2027-04-26 | 10:00 PT convention | SW27 | official |
| 2027 | Fighting Fest | 格鬥遊戲節 | 2027-04-26 | 2027-05-03 | 10:00 PT convention | SW27 | official |
| 2027 | Real-Time Strategy Fest | 即時戰略節 | 2027-05-10 | 2027-05-17 | 10:00 PT convention | SW27 | official |
| 2027 | Mountaineering Fest | 登山遊戲節 | 2027-05-31 | 2027-06-03 | 10:00 PT convention | SW27 | official |

**Not included**
- The 2019–2021 calendars also had smaller ad-hoc Valve sales, such as the 2020 "Tower Defense Tag Sale", and many third-party or publisher sales. I found no confirmed dates for them, so I left them out.
- Steam Next Fest (the free demo festival) is excluded, as requested.

## Start/end time convention

Steam sales and fests open and close at **10:00 AM Pacific**. Valve states this explicitly in many posts:
- "November 22nd at 10am PST (UTC -8) until November 29th at 10am PST (UTC -8)" (2022 Autumn Sale): https://steamcommunity.com/games/593110/announcements/detail/3388424091280374210
- "December 21st (10am Pacific) - January 4th (10am Pacific)" (2023 Winter Sale): https://steamcommunity.com/games/593110/announcements/detail/3902995340341070247
- "October 26 at 10:00 AM PDT (UTC-7) to November 2 at 10:00 AM PDT (UTC-7)" (Steam Scream 2023): https://steamcommunity.com/groups/steamworks/announcements/detail/3719453992471603363
- "Steam's annual Autumn Sale is just days away, kicking off November 21st at 10am Pacific." (Steamworks, 2023): https://steamcommunity.com/groups/steamworks/announcements/detail/3788151013321059167

The Steamworks Upcoming Events and Seasonal Sales docs list calendar dates only, with no time of day.

In UTC, a sale opens and closes at:
- **18:00 UTC** during PST (UTC-8).
- **17:00 UTC** during PDT (UTC-7).

In Taiwan time (UTC+8) that is **02:00** or **01:00** the following day.

## Patterns for estimating sales that are not yet announced

**Weekday.** Since 2022, almost every seasonal sale starts on a **Thursday**.
- Exceptions:
  - Autumn Sales tied to Thanksgiving (2019–2024) started Tue/Wed.
  - The first moved Autumn Sale (2025) started on Monday, Sep 29.
  - Steam Scream and themed fests usually start on **Monday**. Spotlight fests are 4 days, often Thursday to Monday.

**Spring Sale** (from 2023; replaced the Lunar New Year Sale).
- Mid-March, **7 days**, on the 2nd or 3rd Thursday: Mar 16 2023, Mar 14 2024, Mar 13 2025, Mar 19 2026, Mar 18 2027.
- Before 2023, the Lunar New Year Sale ran in late Jan or early Feb for 4 to 7 days.

**Summer Sale**
- Starts on the **last Thursday of June, or the Thursday before it** (Jun 23 to Jun 29). Lasts **14 days** and ends in early to mid July.
- 2019 was an outlier: it started on a Tuesday.

**Autumn Sale**
- 2019–2024: Thanksgiving week, **Tue/Wed before US Thanksgiving to the following Tue/Wed**, 6 to 7 days, ending around Cyber Monday + 1.
- **From 2025 it moved to late September / early October** (2025-09-29 to 10-06, 2026-10-01 to 10-08), 7 days.
- For 2027, expect roughly the last days of September or the first Thursday of October, for 7 days. Treat this as an estimate until Valve publishes H2 2027 dates, likely around Jan/Feb 2027.
- Black Friday now has only a "Special Offers" hub, not a store-wide sale.

**Winter Sale**
- Starts between **Dec 17 and Dec 22** (Thursday in most years) and ends in early January.
- 14 days up to 2024. **18 days in 2025 and 2026** (Dec 18 to Jan 5, Dec 17 to Jan 4).
- For 2027, expect a start around Thu Dec 16 or Dec 23, 2027, ending around Jan 3 to 6, 2028.

**Halloween / Steam Scream**
- Late October to early November, **7 days** since 2022, usually Mon to Mon, ending Nov 1 to 4. Before 2022 it ran 4 to 5 days.

**Announcement cadence**
- Valve publishes each half-year's schedule 6 to 11 months ahead in the Steamworks group. So far:
  - 2025 H2: announced Feb 2025.
  - 2026 H1: announced Jul 2025.
  - 2026 H2: announced Jan 2026.
  - 2027 H1: announced Jul 2026.
- 2027 H2 dates, including the Autumn Sale, Steam Scream and the Winter Sale, are likely around Jan 2027.
- Watch https://partner.steamgames.com/doc/marketing/upcoming_events

## Announced dates for 2026 and 2027 (as of 2026-09-24)

- Autumn Sale 2026: 2026-10-01 → 2026-10-08
- Cooking Fest: 2026-10-12 → 10-19
- Steam Scream V Fest: 2026-10-26 → 11-02
- Auto-Battler RPG Fest: 2026-11-16 → 11-23
- Black Friday Special Offers hub (Nov 2026, dates TBA)
- Winter Sale 2026: 2026-12-17 → 2027-01-04
- 2027 fests: Desktop Companion (Jan 14–18), Shop Keeper (Jan 25–Feb 1), Sheep (Feb 4–8), Couch Co-Op (Feb 8–15), Rhythm (Mar 8–15), Dinos vs. Robots (Mar 29–Apr 5), Racing (Apr 12–19), Witch (Apr 22–26), Fighting (Apr 26–May 3), RTS (May 10–17), Mountaineering (May 31–Jun 3)
- Spring Sale 2027: 2027-03-18 → 2027-03-25
- Summer Sale 2027: 2027-06-24 → 2027-07-08
- Not yet announced: Autumn Sale 2027, Steam Scream 2027 and Winter Sale 2027.
