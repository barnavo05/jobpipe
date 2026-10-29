# JobPipe 🔔

**Job hunting shouldn't mean refreshing 6 portals every morning.**

JobPipe checks company career pages and job portals every day, matches what it finds against what you told it (role, experience, city), and sends you one clean Telegram message with only the jobs that fit. No spam, no repeats, no app to install.

Runs 100% free: GitHub Actions + Supabase free tier + Telegram bot.

**Try it:** [t.me/jobpipe_alerts_bot](https://t.me/jobpipe_alerts_bot). Set up in 20 seconds, then get a digest every morning or send `/jobs` anytime.

---

## How it works

```
 every day 8:17 AM IST (GitHub Actions)
 ┌──────────────────────────────────────────────────────────────┐
 │ 1. COLLECT                                                   │
 │    Company boards (Greenhouse, Lever, Ashby)  official APIs  │
 │    Adzuna India                               free API key   │
 │    Indeed, LinkedIn, Naukri                   via JobSpy     │
 │        ↓ clean, detect city + experience, dedupe             │
 │ 2. STORE   Supabase Postgres (jobs, users, sent, feedback)   │
 │ 3. MATCH   role + experience + city + excludes, ranked       │
 │ 4. NOTIFY  one Telegram digest per user, top 10 new jobs     │
 └──────────────────────────────────────────────────────────────┘
 every 10 min: bot replies to signups and button taps
```

**The trick that keeps it free:** it searches once per *(role, city)* combo, not once per user. 500 people wanting "Data Analyst in Bengaluru" is 1 search, not 500.

**Dedupe:** the same job posted on Naukri, LinkedIn and the company site is stored once (company + title + city fingerprint), so nobody gets it three times.

**Learns a bit:** every digest has 👎 buttons. Thumb down a company twice and it's muted for you.

---

## Setup (about 20 minutes)

### Step 1: Create your Telegram bot
1. Open Telegram, search **@BotFather**, send `/newbot`.
2. Pick a name (e.g. *JobPipe Alerts*) and a username ending in `bot`.
3. Copy the **token** it gives you. That's your `TELEGRAM_BOT_TOKEN`.
4. Optional: `/setdescription` and `/setuserpic` to make it look legit.

### Step 2: Create a free Supabase database
1. Sign up at [supabase.com](https://supabase.com), create a new project. Pick the **Mumbai (ap-south-1)** region and save the database password.
2. Click **Connect** at the top, choose **Session pooler**, copy the URI.
   It looks like `postgresql://postgres.abcd:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres`
3. Replace `[YOUR-PASSWORD]` with your password. That's your `DATABASE_URL`.

> ⚠️ Use the **Session pooler** URL, not "Direct connection". GitHub's runners are IPv4 only and the direct URL is IPv6, so it would fail.

Tables get created automatically on the first run.

### Step 3 (optional): Free Adzuna key
Sign up at [developer.adzuna.com](https://developer.adzuna.com), create an app, copy `app_id` and `app_key`. Adds another solid India source. Skip it and everything still works.

### Step 4: Put the code on GitHub
1. Create a **public** repo (public repos get unlimited free Actions minutes; your users' data lives in Supabase, never in the repo).
2. Push this folder:
   ```bash
   git init && git add . && git commit -m "JobPipe v0.1"
   git branch -M main
   git remote add origin https://github.com/<you>/jobpipe.git
   git push -u origin main
   ```
3. Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:

   | Secret | Required? |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | yes |
   | `DATABASE_URL` | yes |
   | `ADMIN_CHAT_ID` | optional, your chat id for run reports (get it from @userinfobot) |
   | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | optional |

### Step 5: Turn it on and test
1. Go to the **Actions** tab and enable workflows if GitHub asks.
2. Open your bot in Telegram and send `/start`.
3. In Actions, run **Telegram bot replies** manually (Run workflow button). Your bot answers. Finish the signup by tapping the buttons; each tap gets processed on the next run, so hit Run workflow again between taps while testing (or do Step 7 for instant replies).
4. Run **Daily job alerts** manually. Within a few minutes you get your first digest.

From now on it runs by itself every morning.

### Step 6: Check the company list
Run the **Check company boards** workflow. It tests every slug in `config/companies.yaml` and prints how many India jobs each has. Remove the ones that fail, and add companies you care about:

- `job-boards.greenhouse.io/<slug>` → add under `greenhouse:`
- `jobs.lever.co/<slug>` → under `lever:`
- `jobs.ashbyhq.com/<slug>` → under `ashby:`

Tip: this list is the most reliable source you have. 50 to 100 good companies here beats any scraper.

### Step 7 (optional): Instant bot replies with Vercel
By default the bot replies every ~10 minutes. For replies in about a second, free:
1. On [vercel.com](https://vercel.com), sign in with GitHub, click **Add New > Project** and import this repo. No build settings needed: it picks up `api/telegram.py`.
2. Before deploying, open **Environment Variables** and add `TELEGRAM_BOT_TOKEN`, `DATABASE_URL` (same values as your GitHub secrets) and `SUPABASE_POOLER_HOST` (your pooler host, e.g. `aws-1-us-west-2.pooler.supabase.com`). Click **Deploy**.
3. Copy your app URL (like `https://jobpipe-xyz.vercel.app`). In GitHub **Actions**, run **Switch bot reply mode** with mode `instant` and that URL.

That's it. The webhook password is derived from your bot token, so there's no extra secret. The 10-minute bot workflow notices webhook mode and steps aside on its own. To go back, run the same workflow with mode `polling`.

---

## Run it on your laptop

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-full.txt
cp .env.example .env                                   # add your bot token
python -m jobpipe bot              # bot runs live, Ctrl+C to stop
python -m jobpipe collect          # fetch jobs
python -m jobpipe notify --dry-run # print digests instead of sending
python -m pytest -q                # run the tests
```

Without `DATABASE_URL` it uses a local SQLite file, so you can play with zero setup.

## Bot commands
`/start` set up · `/jobs` best new matches right now · `/me` see settings · `/settings` change them · `/exclude intern, sales` hide titles · `/pause` · `/resume` · `/privacy` what's stored · `/stop` deletes all your data

---

## Free tier gotchas (read these)

- **GitHub pauses scheduled workflows** in public repos after 60 days with no commits. Push any small change every month or so (or GitHub emails you, click re-enable).
- **Supabase pauses** projects after a week of no activity. The daily run hits the DB, so this never triggers while it's running.
- **LinkedIn / Indeed / Naukri** don't offer free APIs and block scrapers aggressively. JobSpy failures are logged and skipped, never fatal. Keep `MAX_SEARCH_QUERIES` modest. Company boards and Adzuna are the reliable backbone.
- **Telegram** allows roughly 30 messages a second. One digest per user per day keeps you far below that even at thousands of users.

## Project layout

```
jobpipe/
  sources/ats.py         Greenhouse, Lever, Ashby (official public APIs)
  sources/adzuna.py      Adzuna India API
  sources/jobspy_source  Indeed, LinkedIn, Naukri via JobSpy
  normalize.py           HTML cleanup, city detection, experience extraction, dedupe ids
  roles.py               preset roles and title patterns
  match.py               matching + ranking
  bot.py                 Telegram signup flow and commands
  notify.py              daily digest
  db.py                  SQLite/Postgres storage
api/telegram.py          optional Vercel webhook
config/companies.yaml    company boards to watch
.github/workflows/       daily run, bot polling, board checker, reply mode switch
```

## Privacy

The bot stores a user's Telegram chat id, first name, the preferences they pick, and which jobs it sent them. Telegram never gives bots phone numbers, usernames or contacts. `/stop` deletes everything about a user immediately. Nothing is sold or shared. Secrets (bot token, database URL) live only in GitHub Secrets and never in this repo.

## Disclaimer

This is a personal, non-commercial, educational project. It is not affiliated with or endorsed by LinkedIn, Indeed, Naukri, Glassdoor, Adzuna or any company whose jobs it lists.

- Company career boards (Greenhouse, Lever, Ashby) and Adzuna are read through their official public APIs.
- LinkedIn, Indeed and Naukri do not offer free public APIs. Their listings are fetched at low volume through the open-source [JobSpy](https://github.com/speedyapply/JobSpy) library, which may conflict with those sites' terms of service. If you run your own copy, review those terms, keep volume low, or turn this off with `JOBSPY_ENABLED=0`.
- Every alert links back to the original posting. JobPipe never hosts, edits or republishes full job descriptions, and never applies to jobs on anyone's behalf.
- Listings come from third parties and may be outdated or inaccurate. Always verify a job on the employer's own site before sharing personal details. No job will ever ask you to pay to apply.

Provided as is, without warranty. Use at your own risk.

## Roadmap ideas
- Email digests (Resend free tier) for people who don't use Telegram
- Embedding based matching using the 👍/👎 data
- A small landing page on GitHub Pages with a "Start on Telegram" button
- WhatsApp channel later, once there's a reason to pay for it
