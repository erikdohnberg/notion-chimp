# notion-chimp

Open and click tracking for small email campaigns sent from your own mailbox, with a Notion database as the contact list.

Rows in your database are the contacts. notion-chimp sends each one the right email from your personal Gmail (or any SMTP account), adds a tracking pixel and tracked links, and writes opens and clicks back to properties you choose on that row. A status column drives who gets which email next, so follow-ups happen on schedule without a separate tool.

It's meant for campaigns you'd otherwise run by hand: a few dozen outreach emails, a fundraising ask, a round of partner or sponsor notes. It is not a bulk mailer or a newsletter platform. You host it yourself, so your contacts and engagement data stay in your Notion workspace.

## How it works

1. You describe your database in a YAML config: which property holds the email address, which one is the status, which dates to update, and which (optional) properties receive tracking data. Property names are yours; nothing in the code assumes a particular schema.
2. You define a sequence: "rows with status Ready get `initial.txt`, then move to Contacted with a next action in 7 days", and so on.
3. `notion-chimp run` finds rows that are due, renders each template with that row's properties, and shows you what it would send. `--send` sends them through Gmail (or SMTP) and advances each row.
4. Each HTML email carries a tracking pixel and wrapped links pointing at your tracking server. When the recipient opens the email or clicks a link, the server writes to that row: open count, first opened, link clicked, last engagement.

### Where each piece runs

There are two halves, and they share two settings.

```
 your computer                              Vercel (or any host)
 ─────────────                              ────────────────────
 notion-chimp run --send                    tracking server
   reads due rows from Notion                 /o/<token>.gif  (opens)
   sends through your Gmail  ──> recipient ──>/c/<token>      (clicks)
   updates status and dates                   writes opens/clicks to Notion
```

The sender runs on your own machine, because Gmail's sign-in happens in your browser and the resulting token should stay with you. The tracking server has to be reachable from the internet around the clock, so it runs on a host like Vercel. Both halves need the same `NOTION_CHIMP_SECRET_KEY` (the sender encrypts links with it, the server decrypts them) and the same `NOTION_CHIMP_BASE_URL` (the sender writes it into every email, the server lives there).

## Setup

Do these in order. Budget about 30 minutes the first time.

### 1. Install

Python 3.10+.

```bash
git clone https://github.com/erikdohnberg/notion-chimp.git
cd notion-chimp
python -m venv .venv && source .venv/bin/activate
pip install -e '.[gmail]'
cp .env.example .env
```

`.env` holds your local secrets and is gitignored. You'll fill it in over the next steps.

### 2. Notion integration and token

1. Create an integration. In Notion, go to Settings, then Connections, then "Develop or manage integrations", and create a new internal integration for your workspace. It needs "Read content" and "Update content". It does not need "Insert content" or any user information.
2. Copy the integration secret (it starts with `ntn_` or `secret_`) and put it in `.env`:

   ```bash
   NOTION_TOKEN=ntn_...
   ```

   You'll add the same value to Vercel in step 4. Never put it in a config file or commit it.
3. Share the database with the integration. Open the database page, use the `•••` menu, choose Connections, and add your integration. Without this step every API call returns 404.
4. Get the data source URL. Open the database, use "Copy link" or look under "Manage data sources" for a `collection://...` URL. It goes in your config as `notion.data_source`. A regular database URL also works if the database has a single data source.
5. Add the tracking properties you want, by hand. notion-chimp never creates, renames or deletes properties. Suggested types:

| Role | Suggested type |
| --- | --- |
| open_count | Number |
| first_opened | Date |
| link_clicked | Checkbox, or Date if you want to know when |
| last_engagement | Date |

Any of these can be left out of the config and notion-chimp will skip it.

### 3. Tracking secret key

```bash
notion-chimp gen-key
```

Put the output in `.env` as `NOTION_CHIMP_SECRET_KEY`. Keep it stable. Tracking links are encrypted with it, so changing it breaks every link you've already sent.

### 4. Deploy the tracking server to Vercel

The repo root has an `app.py` and `requirements.txt`, so Vercel runs it as a Flask app with no build step. Your real config goes into an environment variable, so you can deploy straight from the public repo (or your fork) without committing anything private.

1. In Vercel, choose Add New, then Project, and import the repository. Vercel detects the Flask preset. Leave the root directory, build command and output directory at their defaults.
2. Before the first deploy, add these environment variables (Production, and Preview if you want previews to work). Mark the secrets as Sensitive.

   | Variable | Value |
   | --- | --- |
   | `NOTION_TOKEN` | The integration secret from step 2 |
   | `NOTION_CHIMP_SECRET_KEY` | The key from step 3. It must match your local `.env` exactly. |
   | `NOTION_CHIMP_CONFIG_YAML` | The entire contents of your config file (see [Configuration](#configuration)). The server ignores the templates, so paste the whole file as is. |

3. Deploy.
4. Open Settings, then Deployment Protection, and make sure Vercel Authentication does not cover production (set it to "Only Preview Deployments" or turn it off). If it's on, every pixel and link your recipients load hits a Vercel login page and nothing gets tracked.
5. Find the production domain under Settings, then Domains. It looks like `notion-chimp-yourname.vercel.app`. Use this stable domain, not the per-deployment URL with a hash in it.
6. Add `NOTION_CHIMP_BASE_URL=https://notion-chimp-yourname.vercel.app` in two places: as a Vercel environment variable and in your local `.env`. Then redeploy from the Deployments tab, because Vercel only applies environment changes to new deployments.
7. Visit `https://notion-chimp-yourname.vercel.app/healthz`. You should see `"notion_token_set": true` and `"secret_key_set": true`. The endpoint reports whether each secret is present without revealing it.

Vercel deploys your production branch (usually `main`) automatically on every push. If you change your config later, update `NOTION_CHIMP_CONFIG_YAML` and redeploy.

A custom domain is worth considering once things work. Links pointing at a domain you own look more trustworthy to recipients and to spam filters than a `vercel.app` subdomain. Add it under Settings, then Domains, and update `NOTION_CHIMP_BASE_URL` in both places. Links already sent keep working only while the old domain stays attached.

Three differences from a long-running server: writes to Notion happen before the response (Vercel can freeze a function as soon as it responds), the dedupe window is per function instance so a few extra repeat opens may count, and the kill switch file doesn't apply. To stop write-back on Vercel, set `NOTION_CHIMP_KILL_SWITCH=1` there and redeploy.

Prefer another host? See [The tracking server](#the-tracking-server) for gunicorn and Docker.

### 5. Connect Gmail

notion-chimp asks only for the `gmail.send` scope. It can send as you; it cannot read, search or delete your mail.

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project (any name) and enable the Gmail API for it.
2. Configure the OAuth consent screen. Choose External, fill in the app name and your email, skip the optional scopes screen, and add your own Gmail address as a test user.
3. Under Credentials, create an OAuth client ID of type "Desktop app". Download the JSON and save it as `credentials.json` in the project folder.
4. Run:

   ```bash
   notion-chimp -c my-config.yaml auth-gmail
   ```

   A browser window opens. Sign in with the account you want to send from and approve. Google will warn that the app is unverified, which is expected for an app you made yourself; continue. `token.json` is saved next to `credentials.json`. Both are gitignored and should never leave your machine.
5. Set `sender.from_address` in your config to that same Gmail address. Gmail rewrites the From header to the authenticated account anyway, so a mismatch just produces confusing output.

While the consent screen is in "Testing" status, Google expires the refresh token after 7 days and sends start failing with an auth error. Rerun `auth-gmail` when that happens, or publish the app from the consent screen page (it can stay unverified for personal use) to remove the limit.

To send through another provider, set `sender.provider: smtp` and the `SMTP_*` variables in `.env`. Adding a provider means writing a class with a `send(email) -> message_id` method and registering it in `notion_chimp/senders/__init__.py`. The tracking core never sees which sender was used.

### 6. Write your config and check it

Copy [`examples/sponsor-outreach/`](examples/sponsor-outreach/) into the gitignored `local/` folder, edit the config and templates (details below), then:

```bash
notion-chimp -c local/my-campaign/config.yaml check
```

`check` confirms every mapped property exists with a compatible type, that each step's statuses are real options, and that every `{placeholder}` in your templates is a property. It changes nothing.

### 7. Send yourself a test

Follow [Testing end to end](#testing-end-to-end) before emailing anyone real.

## Environment variables

| Variable | Needed by | Purpose |
| --- | --- | --- |
| `NOTION_TOKEN` | sender, server | Notion integration secret |
| `NOTION_CHIMP_SECRET_KEY` | sender, server | Encrypts tracking links. Same value in both places. |
| `NOTION_CHIMP_BASE_URL` | sender, server | Public URL of the tracking server, no trailing slash. Same value in both places. |
| `NOTION_CHIMP_CONFIG_YAML` | server | Whole config as text, for hosts that deploy from the repo (Vercel) |
| `NOTION_CHIMP_CONFIG` | either | Path to a config file, used when `-c` isn't given (default `notion-chimp.yaml`) |
| `NOTION_CHIMP_KILL_SWITCH` | sender, server | `1` stops all sending and all Notion write-back |
| `GMAIL_CREDENTIALS_FILE` | sender | OAuth client file (default `credentials.json`) |
| `GMAIL_TOKEN_FILE` | sender | Saved Gmail token (default `token.json`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` | sender | Only for the SMTP sender |
| `NOTION_CHIMP_ENV_FILE` | either | Load a different env file instead of `.env` |

The sender reads `.env` from the current directory automatically. `.env.example` lists the same variables with comments.

## Configuration

Start from [`examples/sponsor-outreach/config.yaml`](examples/sponsor-outreach/config.yaml), which is commented line by line. Keep your copy in `local/` (gitignored) or anywhere outside the repo. The parts that matter, with property names from a hypothetical database (use your own):

```yaml
properties:
  email: Contact Email or Route   # any text works; the first address found is used
  status: Status                  # Select or Status type
  last_touch: Last Touch
  next_action_date: Next Action Date
  open_count: Open Count
  first_opened: First Opened
  link_clicked: Brochure Clicked
  last_engagement: Last Engagement

sequence:
  - name: initial
    when_status: Ready
    template: templates/initial.txt
    set_status: Contacted
    next_action_in_days: 7
```

A row is due for a step when its status equals `when_status` and its next action date is empty or not in the future. After sending, notion-chimp sets the status to `set_status`, sets last touch to today and moves the next action date forward (or clears it when `next_action_in_days` is omitted). Rows with any other status are never touched, so setting a row to "Declined" or "In conversation" takes it out of the sequence.

Values like `${NOTION_CHIMP_BASE_URL}` are read from the environment. Secrets belong in `.env`, never in the config.

### Templates

Plain text. The first line is the subject; the body follows a blank line.

```
Subject: Quick question for {Company}

Hi {Contact Name|there},

Details are here: [One-pager](https://example.com/one-pager.pdf)
```

`{Property Name}` inserts that property's value. `{Property Name|fallback}` uses the fallback when the row is empty; without a fallback an empty value skips the row rather than sending "Hi ,". Links can be bare URLs or `[text](url)`. Each email goes out as plain text plus HTML, and only the HTML part is tracked.

## Running a campaign with Gmail, end to end

Once setup is done, a campaign is a Notion database plus one command a day.

1. Fill the database. Add a row per contact with an email address somewhere in the email property. Free text like "Jane <jane@shop.com>" or "jane@shop.com (owner)" is fine; the first address found is used. Rows without one are listed as skipped, never guessed.
2. Mark who's ready. Set the status of rows you want to contact to your first step's `when_status` (for example Ready). Leave the rest in a status the sequence doesn't use, like Researching.
3. Preview:

   ```bash
   notion-chimp -c local/my-campaign/config.yaml run
   ```

   You get one line per due row: the step, the recipient and the rendered subject, or the reason it would be skipped. Nothing is sent and nothing in Notion changes.
4. Send:

   ```bash
   notion-chimp -c local/my-campaign/config.yaml run --send --limit 10
   ```

   Each email goes out through the Gmail API as a normal message from your account. It appears in your Sent folder, replies land in your inbox, and the recipient sees an ordinary email from you, not from a mailing service. After each send, the row's status, last touch and next action date are updated.
5. Watch Notion. Opens and clicks arrive on the rows within seconds as recipients engage. Sort or filter by last engagement or link clicked to see who to call.
6. Handle replies yourself. notion-chimp can't read your mail, so it doesn't know when someone answers. When a person replies, change their row's status to something outside the sequence (In conversation, Declined, Committed). Rows in those statuses never get another automated email.
7. Run it again each day. Follow-ups go out as rows come due. Running `run --send` daily is enough; rows that aren't due are left alone, so running it twice in one day sends nothing new. Schedule it with cron on a machine that's usually on, or just run it with your morning coffee.

Things worth knowing before you send to real people:

- Sending limits. Google caps how many recipients a Gmail account can send to per day (at the time of writing, around 500 for a regular Gmail account and 2,000 for Google Workspace; check Google's "Gmail sending limits" page for current numbers). Staying well below that, and using `--limit` to spread a big first wave over a few days, also helps you stay out of spam folders.
- Follow-ups start a new thread. Each step is sent as a new message. If you want a follow-up to read as part of the conversation, write it that way ("Following up on my note from last week") rather than relying on threading.
- Keep it personal. These emails come from your real address, so a recipient marking one as spam affects your mailbox's reputation. Short, specific, plainly written emails to people who have a reason to hear from you are what this tool is for.
- Stop everything at once with the kill switch (see below) if something looks wrong mid-send.

## The tracking server

The server has two routes:

- `GET /o/<token>.gif` returns a 1x1 transparent GIF and records an open.
- `GET /c/<token>` redirects to the original link and records a click.

Tokens are encrypted with your secret key, so recipients can't see row ids and nobody can use your server as an open redirect. Recipients always get their image or their redirect, even when a hit is filtered, the kill switch is on, or Notion is unreachable. Only the write-back is skipped. `GET /healthz` reports whether the kill switch is on and whether the Notion token and secret key are set.

Setup step 4 covers Vercel. Run it locally with `notion-chimp -c my-config.yaml serve`, or on any other host behind HTTPS with gunicorn:

```bash
pip install '.[server]'
NOTION_CHIMP_CONFIG=my-config.yaml gunicorn -w 2 -b 0.0.0.0:8000 notion_chimp.wsgi:app
```

A `Dockerfile` is included. Set `NOTION_CHIMP_BASE_URL` to the public URL before sending anything, because that URL is baked into every email.

### Filtering false opens and clicks

A lot of what hits a tracking pixel isn't a person. notion-chimp ignores:

- HEAD requests, which scanners use to probe links.
- Opens within `min_seconds_after_send` (default 30s) and clicks within `click_min_seconds_after_send` (default 10s). Security gateways fetch images and follow every link as soon as a message lands.
- User agents matching known scanners and HTTP libraries (Barracuda, Mimecast, Proofpoint, curl, python-requests and others; editable in the config).
- Apple Mail Privacy Protection prefetches, when `apple_mpp: skip` (the default). See below.
- Repeat opens of the same email within `dedupe_minutes` (default 30). This window is kept in memory, so a server restart can let one extra open through.
- Any IP in `ignore_ips`.

### Kill switch

Set `NOTION_CHIMP_KILL_SWITCH=1` or create the file named in `kill_switch.file` (default `./KILL`). While it is on, `run --send` and `test-send` refuse to send, and the server stops writing to Notion while still serving pixels and redirects. It's checked on every request and every send, so the file version takes effect without a restart.

## How open tracking accuracy actually works

Open tracking works by embedding a tiny image and noticing when it's downloaded. Every open-tracking tool, including the expensive ones, relies on this, and it is unreliable in both directions. Treat open counts as a rough signal. Replies are the only engagement signal you can fully trust; clicks come second.

Gmail's image proxy. Gmail fetches images through its own proxy (the user agent includes `GoogleImageProxy`) and caches them. The first open of a message reaches your server and is counted. Later opens are often served from Google's cache and never reach you, so repeat opens from Gmail users are undercounted. You also never see the reader's IP address or device.

Apple Mail Privacy Protection. When an Apple Mail user has MPP enabled, which is the default for most of them, Apple downloads every image in every message through its proxy shortly after delivery, whether or not the person ever opens it. Those requests arrive with a bare `Mozilla/5.0` user agent. notion-chimp skips them by default, which means real opens from Apple Mail users are mostly invisible. Set `apple_mpp: count` if you'd rather accept a flood of opens that didn't happen. Neither setting tells you the truth about Apple Mail readers; there is no way to.

Clients that block images. Outlook desktop, many corporate environments and privacy-minded people block remote images until the reader allows them. Those opens are never seen. Plain-text readers never load the pixel either.

Security scanners. Corporate mail gateways often download images and follow every link before the recipient sees the message. The time window and user agent list catch most of this, but new scanners appear and some imitate real browsers, so an occasional scanner will get through as a "click" in the first minutes after sending.

Your own opens. If you open your sent copy in Gmail, the pixel loads through the same proxy a recipient's would, and notion-chimp cannot tell the difference. Avoid opening sent copies, or turn off image loading for your own account. For testing, send to a separate address (see below).

In practice: an open count of zero doesn't mean the email went unread, and one open doesn't prove a person read it. A link click after the first few minutes is a much stronger signal, which is why the example config tracks a brochure link.

## Testing end to end

The safest test is one fake row and one email to yourself.

1. Add a test row to the database with a name you'll recognize, a status matching your first step, and any email address. The address is ignored in step 2.
2. Send that row's email to yourself without advancing it:

   ```bash
   notion-chimp -c my-config.yaml test-send --page <row URL> --to you+test@example.com
   ```

   The subject is prefixed with `[TEST]`. Add `--advance` to also move the row's status and dates.
3. Wait at least 30 seconds, then open the email in the recipient's inbox (not your Sent folder). Within a few seconds the row's open count should read 1, and first opened and last engagement should be set.
4. Click the link. The link-clicked property should update and you should land on the real page.
5. Delete the test row when you're done.

The server must be reachable at `NOTION_CHIMP_BASE_URL` from the internet for steps 3 and 4. For a quick local test, a tunnel such as `cloudflared tunnel --url http://localhost:8000` works.

Unit tests run without Notion or Gmail:

```bash
pip install -e '.[dev]'
pytest
```

## Example: sponsor outreach

[`examples/sponsor-outreach/`](examples/sponsor-outreach/) is a complete setup for a common case: finding sponsors for a small event. Each row is a local business, the sequence is an intro email and two follow-ups a week apart, and the tracked link is the sponsor package. To adapt it, copy the folder, point `data_source` at your database, change the property names on the right-hand side to match yours, and rewrite the templates. If your statuses are different, change `when_status` and `set_status` to match.

Keep your real config and templates outside the repo, or in the gitignored `local/` folder, so your database id and contact details never get committed.

## License

MIT. See [LICENSE](LICENSE).
