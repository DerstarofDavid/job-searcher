# David’s Job Finder

This is a runnable, local program for the Swiss job-search workflow we developed. It discovers openings, verifies public job pages when permitted, extracts structured job details, applies David’s exact exclusions and profile rules, ranks matches from 1–10, remembers earlier results, and creates a readable HTML report.

It is designed for Windows and uses only Python’s standard library. Bing RSS and DuckDuckGo work without an account or API key. Tavily can be added as an optional third discovery source.

## What it searches

The default **deep** run executes roughly 60 targeted queries across:

- Indeed, LinkedIn’s public index, jobs.ch, JobScout24, OSTJOB, jobup, JOIN, Workday, Ashby, talendo and professional.ch
- Public employer career pages for consulting, finance, insurance, technology and ERP-adjacent firms
- Business Central / AL, ERP and application consulting/support
- Business analysis, finance transformation/automation, technology risk, IT audit and controls
- PMO/CIO office, digital processes, QA/testing, supply chain/procurement/master data, operations and SaaS customer success

The saved filter prioritizes 20–60% roles around St. Gallen, Eastern Switzerland, Frauenfeld, Winterthur and Zürich/hybrid. It prefers English listings, accepts German roles that appear realistic at B2, and rewards employers that signal junior, student, trainee, entry-level or learning-on-the-job openness.

A **Senior** title is not an automatic rejection. It stays as a stretch match unless the page actually requires experience or responsibility beyond the profile.

The current configuration already excludes the supplied applied/waiting, rejected and previously reviewed companies. Edit [`config/job_filter.json`](config/job_filter.json) or use the company commands described below whenever the status changes.

## Windows: first setup

1. Install [Python 3.11 or newer](https://www.python.org/downloads/windows/) if it is not already installed. Select **Add Python to PATH** during installation.
2. Extract this folder somewhere permanent, such as `Documents\Davids-Job-Finder`.
3. Double-click `setup_windows.bat`.
4. Double-click `run_demo.bat`. It uses five bundled sample pages and opens a demonstration report without internet access.
5. Double-click `run_now.bat` for the real deep search.

The live run normally takes 20–60 minutes because it deliberately searches many combinations, limits request speed, checks robots.txt, and verifies public pages one by one. The latest results are always in `reports\latest.html`; `open_latest_report.bat` opens it again later.

## Run every weekday

After setup, open PowerShell in the project folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\schedule_weekdays.ps1 -At "09:00"
```

This creates a Windows Task Scheduler entry for Monday–Friday at 09:00. Scheduled output is appended to `logs\daily.log`. To change the time, rerun the command with another `HH:mm` value; it updates the same task.

## Command-line use

From the project folder, these commands work after setup:

```powershell
.\.venv\Scripts\python.exe -m jobfinder doctor
.\.venv\Scripts\python.exe -m jobfinder demo --open
.\.venv\Scripts\python.exe -m jobfinder scan --mode quick --provider auto --open
.\.venv\Scripts\python.exe -m jobfinder scan --mode deep --provider auto --open
```

Search modes:

- `quick`: 6 broad queries for a fast check
- `standard`: 21 broad and role-specific queries
- `deep`: all standard queries plus site-specific searches across every configured job board and career domain

## Keep application history current

When you apply or receive a rejection, update the exclusion file through the program:

```powershell
.\.venv\Scripts\python.exe -m jobfinder company add "Example AG" --status applied
.\.venv\Scripts\python.exe -m jobfinder company add "Other AG" --status rejected
.\.venv\Scripts\python.exe -m jobfinder company list
```

Valid statuses are `applied`, `waiting`, `rejected`, and `blocked`. To undo a status:

```powershell
.\.venv\Scripts\python.exe -m jobfinder company remove "Example AG" --status applied
```

## Optional Tavily search

The program does not require Tavily. A light, rate-limited keyless mode is available with `--provider tavily`. For dependable daily use, copy `.env.example` to `.env` (setup does this automatically) and set a Tavily API key:

```text
TAVILY_API_KEY=your_key_here
```

With `--provider auto`, Tavily is used alongside the two other providers—up to 8 queries in keyless mode or 12 with a key. This limit controls rate usage and credits; change `tavily_auto_max_queries` in the configuration if desired. You can also use `--provider tavily` to use it alone. See the [official Tavily Search API documentation](https://docs.tavily.com/documentation/api-reference/endpoint/search). Keep `.env` private; it is excluded from archives and version control.

## Optional alerts

Email and Telegram alerts are disabled by default. Enable either in `config/job_filter.json`, then fill the matching `JOBFINDER_...` values in `.env`. Alerts include only newly found openings at or above the configured 8/10 threshold. A notification failure is recorded as a warning and does not discard the report.

## Report structure

Every run creates timestamped Markdown, HTML and JSON files, plus `latest.*` copies. The HTML report contains:

1. Top opportunities at 6/10 or above, ranked and linked
2. Location, workload, verification status, fit evidence and specific gaps
3. Borderline 4–5.9/10 opportunities with concise risk notes and links
4. 2–3/10 discoveries as company and title only, without links
5. Removed results and the exact reason (prior application, location, workload, language, experience, degree requirement, expiry, and so on)
6. Source-health details, so a blocked or failing search source is visible instead of silently creating false confidence

The SQLite file at `data/jobfinder.sqlite3` retains first-seen and last-seen history so repeat scans can label genuinely new opportunities.

## Responsible scraping boundary

This program reads only public pages, identifies itself with a low-rate user agent, checks robots.txt, limits page sizes, and spaces requests by domain. It does **not** bypass CAPTCHAs, authentication, paywalls or anti-bot controls.

LinkedIn and Indeed often restrict automated page access. Their public search-index results can still help discover an opening, but when the actual page cannot be verified the report clearly says **Needs verification**. Always open the employer/job-board page before applying. No search tool can honestly guarantee it found every opening on the internet; source-health reporting makes gaps explicit.

## Files and privacy

- Search history and reports remain in this folder.
- API keys and mail credentials remain in `.env` and are never written to reports.
- The program does not submit applications or send your CV.
- Deleting `data/jobfinder.sqlite3` resets the discovery history; keep a backup if the history matters.

## Troubleshooting

- Run `setup_windows.bat` again if Python was upgraded or the `.venv` folder is missing.
- Run `python -m jobfinder doctor --show-queries` to inspect the exact deep-search coverage.
- Check `logs\daily.log` if a scheduled run did not produce a new report.
- Search sources can temporarily throttle or change their HTML. The report’s source-health section will show the failure, while the remaining providers continue.
