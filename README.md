# Design Jobs Radar

A free website that updates itself every day with brand and graphic design vacancies
(UK, Europe, and remote roles that suit someone based in Malta), and sends you a
notification each morning with what is new.

It runs on GitHub (free): GitHub Actions does the daily fetching, and GitHub Pages hosts the site.
Nothing runs on your computer.

## One-time setup (about 20 minutes)

1. **Create a GitHub account** at github.com (skip if you have one).
2. **Create a new repository** (the + button, top right). Name it `design-jobs-radar`, set it to **Public**
   (free GitHub Pages needs a public repo), then create it.
3. **Upload this folder's contents.** On the new repo page choose *uploading an existing file* and drag in
   everything from the unzipped folder. The `.github` folder is hidden on some computers: on a Mac press
   `Cmd + Shift + .` in Finder to show it. The `.github/workflows/daily.yml` file must be uploaded, because it is the daily timer.
   Commit the upload.
4. **Turn on the website:** repo *Settings → Pages → Build and deployment → Deploy from a branch*,
   branch `main`, folder `/docs`, Save. Your site will be at `https://YOUR-USERNAME.github.io/design-jobs-radar/`.
5. **Set up the morning notification** (pick email, Telegram, or both). *Settings → Secrets and variables → Actions → New repository secret*:

   **Email (Gmail example)**
   - Turn on 2-Step Verification on your Google account, then create an *App password* (Google Account → Security).
   - Add these secrets: `SMTP_HOST` = `smtp.gmail.com`, `SMTP_PORT` = `465`, `SMTP_USER` = your Gmail address,
     `SMTP_PASS` = the app password, `EMAIL_TO` = where to send it (one or more addresses, comma separated).

   **Telegram (instant on your phone)**
   - In Telegram, message `@BotFather`, send `/newbot`, and copy the token. Send any message to your new bot, then open
     `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the number after `"chat":{"id":`.
   - Add secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
6. **Run it once now:** repo *Actions* tab → *Daily design jobs update* → *Run workflow*.
   After about a minute the site fills with vacancies. From then on it runs by itself every day at 06:00 UTC
   (07:00 Malta time in winter, 08:00 in summer; GitHub can delay scheduled runs by a few minutes).

## Optional upgrades

- **More UK and European listings (Adzuna).** Get a free developer key at developer.adzuna.com and add secrets
  `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`. These listings usually do not mention sponsorship, so they are only kept
  when the advert says so or the employer is on the UK sponsor register (next item).
- **UK licensed sponsor badge.** Download the *Register of licensed sponsors: workers* CSV from GOV.UK, save it as
  `data/sponsors.csv` in the repo, and refresh it every month or two. UK jobs from employers on that list get an
  "On UK sponsor register" badge. Being on the list means the employer can sponsor; it does not mean they will sponsor this role.
- **Change what counts as a match.** Edit `config.json`: job-title patterns, excluded titles, countries, how many days to keep jobs,
  and `send_when_empty` (set to `true` if you want a message even on days with no new jobs).

## What the site does

Search, filter by country, and filter by New, Visa / relocation, Remote, UK licensed sponsor. You can Save, mark Applied, or Hide
each vacancy. Those choices are stored only in your own browser. There is also a panel of daily search shortcuts for boards
that have no free feed (LinkedIn, Indeed, Google Jobs and others), and a feed-status panel that shows if a source broke.

## Good to know

- Sources: Arbeitnow (Germany/DACH and UK, with its own visa-sponsorship filter), Jobicy and Remotive (remote), and Adzuna if enabled.
  If a source changes or goes down, the others keep working and the failure is listed on the site and in the email.
- Sponsorship detection reads the advert wording, so treat every badge as a lead to confirm with the employer.
- GitHub pauses scheduled runs on repositories with no activity for 60 days. The daily commits normally keep it active;
  if the emails ever stop, open the Actions tab and re-enable the workflow.
- Test the matching logic offline any time: `python scripts/fetch_jobs.py --selftest`.
