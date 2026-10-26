# Bodycam Research Hub

A local research dashboard for a police-bodycam YouTube channel. Every morning it shows you:

* **recent, interesting incidents** in your chosen states (FL, OH, WI, TX, PA, CA by default), from real news and police sources
* **whether they're already on YouTube**: bodycam uploads vs. news coverage vs. commentary
* **whether footage probably exists**, and **exactly where to request it**: the agency, its verified records portal, records e-mail, fees and state-law requirements
* a **0-100 opportunity score** with a full breakdown and editorial risk flags
* a **records request generator** and a **request tracker**

Everything runs on your PC (Python + Streamlit + SQLite). There's no hosting and no subscription. API usage and agency records fees may still cost money.

---

## 1. Windows setup (one time)

1. Install **Python 3.12 or newer** from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**.
2. In this folder, double-click **`setup.bat`**. If you prefer the command line, run this in PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
   ```
   It creates a `.venv`, installs `requirements.txt`, creates `.env` and initializes the database.
3. Double-click **`start_app.bat`**. The dashboard opens at <http://localhost:8501>.
4. Go to **Settings**:
   * **API keys**: add your YouTube key (see below), then click **Test YouTube key**.
   * **My details**: your name, e-mail and mailing address, used in generated requests.
5. On **Overview**, click **Run Research Now**. A full run takes about 3-8 minutes and runs in the background, so you can keep browsing.

### Getting a YouTube Data API key (free)
1. Go to <https://console.cloud.google.com/>, then create a project.
2. Open **APIs & Services → Library**, search for **YouTube Data API v3** and click **Enable**.
3. Open **APIs & Services → Credentials → Create credentials → API key**. Restrict the key to *YouTube Data API v3*.
4. Paste the key into Settings → API keys.

The default quota is **10,000 units/day**. A video search costs 100 units and a details lookup costs 1, so the app checks about 25 cases per run by default and keeps a local daily budget (Settings → Research). All results are cached.

### Optional keys
| Key | What it adds |
|---|---|
| `AI_PROVIDER` + `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | AI interest/footage estimates (always labelled as estimates) and request-letter polishing |
| `BRAVE_SEARCH_API_KEY` | Better discovery of agency websites that aren't on obvious `.gov` domains |

The app works fully without these.

---

## 2. Daily automatic research (no browser needed)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Time 06:30
```
This registers a Windows Task Scheduler job that runs `run_research.py` silently every day. If the laptop was asleep at that time, the job runs as soon as it wakes. To test it immediately:
```powershell
Start-ScheduledTask -TaskName "Bodycam Research Hub - Daily Research"
```
To remove it: `scripts\unregister_daily_task.ps1`. There's also `python run_research.py --schedule` (APScheduler) if you'd rather keep a window open.

Other options: `python run_research.py --skip-youtube` and `--skip-records`.

---

## 3. Pages

| Page | What it's for |
|---|---|
| **Overview** | Key numbers, **Run Research Now**, top opportunities, run history and logs |
| **Discover Cases** | Searchable, sortable table with filters (state, place, type, date window 7-90 days, score, bodycam status, YouTube status, request status, expected cost, saved/hidden). Save or hide cases. |
| **Case Research** | Three columns: **criminal case** (summary, date/location with provenance, agency, sources, timeline), **YouTube** (thumbnails, views, match %, footage flag), **footage acquisition** (agency, **Open Records Request Portal**, e-mail, law, fees, instructions, request status). Score breakdown and risk flags appear below. |
| **YouTube Competition** | Tracks channels such as **@CodeBlueCam** (pre-loaded as a handle and resolved through the API): uploads per week, views, incident types and states covered, and which of your cases they've already covered |
| **Footage Request Research** | Verify or correct agency contact details, see state law (deadlines, required elements, fees), and **Generate Records Request** to copy, download, open an e-mail draft, or save to the tracker |
| **Request Tracker** | Statuses Researching through Closed, with tracking number, quoted fee, amount paid, follow-up date, response and notes. Editable table, follow-up reminders, CSV export |
| **Agencies and Sources** | All agencies, plus your own RSS feeds (police newsrooms, local TV) with a feed tester and a "find feeds on this page" helper, and extra counties/cities/agencies to search |
| **Settings** | Keys, states, incident types, lookback, limits, budget, your details, schedule, cache and export |

---

## 4. How accuracy is protected

**Nothing is invented.** Every case comes from a real article or feed item, and its sources are linked. If a field can't be found, it's shown as unknown.

Each extracted fact carries a **basis**, colour-coded in the UI:

| Colour | Meaning | Examples |
|---|---|---|
| Green | Verified / stated in the source | "date stated in source", "named in source", portal found on the agency's own .gov site |
| Amber | Likely but unconfirmed | agency inferred from "Tampa police" wording, date derived from "Tuesday night" |
| Purple | Estimate (rules or AI) | "Likely exists (estimate)", AI interest score, cost estimate |
| Grey | Missing / not checked | "not stated in checked sources", YouTube "Not checked" |

**Incident date vs. publish date.** The incident date comes only from the text ("Oct. 18", "Tuesday night", "yesterday"), and the evidence is quoted. Court and hearing dates are ignored. The publish date is shown separately.

**Records portals.** The **Open Records Request Portal** button only appears when the link was:
* found on the agency's own **.gov** website, on a page that names the agency, **or**
* confirmed by you ("Mark verified", or typed in on the Footage page).

Links found anywhere else are listed as *unverified candidates*, and you have to verify them before they're shown as the portal. If nothing is verified, the app says so. The app never builds a URL or e-mail address and presents it as real. Candidate `.gov` hostnames are only kept if they load *and* name the agency.

**YouTube.** "No match in checked results" means exactly that, not "never uploaded". News coverage and actual footage are tracked separately. A matched video is flagged as footage only when its title or description says bodycam, dashcam or similar.

**Polite collection.** The app uses official APIs and RSS feeds wherever possible. It checks robots.txt before fetching any web page, waits between requests to the same site, and caches responses. When a site shows a CAPTCHA, login, paywall, or returns 401/403/429, the app records it and moves on. It never tries to get around access controls.

**Nothing is submitted or paid automatically.** Requests are drafts that you copy and send yourself.

**State law summaries** in `bch/state_laws.py` for FL, OH, WI, TX, PA and CA were checked against the linked sources in October 2026. They are informational, not legal advice. Key points:
* **PA**: Act 22 bodycam requests must be made within **60 days**, by certified mail or in person. The app warns you as the deadline approaches.
* **TX**: §1701.661 requires the date, approximate time, location and the **name of a person recorded**.
* **OH**: HB 315 lets agencies charge up to **$75/hr, capped at $750**.
* **WI**: minimum retention is **120 days**.
* **CA**: §7923.625 has a 45-day timeline for critical incidents.

---

## 5. Scoring (0-100)

| Component | Max | Based on |
|---|---|---|
| Interest / unusualness | 25 | incident type + unusual elements (tractor, wrong-way, naked, K9...) + AI estimate if enabled |
| Audience potential | 10 | number of outlets covering it |
| Footage likely exists | 15 | released > mentioned > likely (estimate) > unknown |
| Not already on YouTube | 15 | no matching upload in checked results scores highest |
| YouTube competition | 10 | number and views of matching videos |
| Recency | 10 | days since the incident |
| Ease of acquisition | 10 | verified portal, plus state rules (PA 60-day window, TX name requirement, WI retention, ongoing investigation) |
| Source reliability | 5 | official source / multiple outlets / agency named |
| Risk penalties | − | minors, victims, graphic content, monetization risk |

Risk indicators (minors, victims, graphic content, ongoing investigation, privacy, YouTube ad-suitability) come from keyword matches, and the matching text is shown.

---

## 6. Project layout

```
app.py                  Streamlit entry point (navigation)
run_research.py         CLI runner (Task Scheduler / --schedule)
bch/
  config.py  db.py  models.py        settings, SQLAlchemy engine, ORM models
  net.py                              robots.txt, rate limiting, caching, restriction detection
  feeds.py  discovery.py              RSS parsing, Google/Bing News, custom feeds, article reading
  analysis.py                         relevance, categories, agency/location/date extraction, dedupe, risk flags
  youtube.py                          YouTube Data API, match scoring, competitor channels
  records.py  state_laws.py           custodian research, portal/e-mail/fee discovery, law summaries
  request_writer.py                   records request drafts
  scoring.py  ai.py                   opportunity score, optional AI
  pipeline.py  services.py            research pipeline, UI data helpers
  ui/                                 one module per page
tests/                  unit, end-to-end pipeline (fake network) and headless UI tests
scripts/                Windows setup + Task Scheduler scripts
```

**Data location:** on Windows the database (`bodycam_hub.sqlite3`) and logs live in `%LOCALAPPDATA%\BodycamResearchHub`, *not* in this OneDrive folder, because syncing a live SQLite file can corrupt it. Override with `BCH_DATA_DIR` in `.env`.

**Tests:** `run_tests.bat` or `.venv\Scripts\python.exe -m pytest -q`. They need no internet: the network is faked with fixtures using fictional incidents and example domains.

---

## 7. Known limits and tips

* **Google News** links open through Google's redirect, so the app can't read the full article from them. **Bing News** links point straight to the publisher, so those articles are read (if robots.txt allows) for dates, names and bodycam mentions. Keep both enabled.
* The best sources are **official agency feeds**. Many sheriff and police newsrooms publish RSS. Add them under Agencies and Sources and tick **Official agency**.
* Agency extraction is rule-based. If a case shows the wrong agency, use **Reassign agency** on the Footage page.
* Many agencies use third-party portals (NextRequest, GovQA, JustFOIA). These are detected and trusted when linked from the agency's own .gov site.
* Sheriffs on `.org`/`.com` domains won't be auto-verified. Open the candidate link once and click **Use + verify**.
* To add a state, select it in Settings. To add its law summary, edit `bch/state_laws.py`.
