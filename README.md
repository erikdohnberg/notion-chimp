# notion-chimp

Run an outreach sequence straight from a Notion database. Rows in your database are the contacts, a status column drives which email each one gets next, and opens and clicks are written back to properties you choose. You host it yourself, so your contact list and engagement data stay in your Notion workspace and nowhere else.

It is built for small, personal campaigns: sponsor outreach for an event, a fundraising push, a round of partner emails. It is not a bulk mailer, and it deliberately sends from your own mailbox.

## How it works

1. You describe your database in a YAML config: which property holds the email address, which one is the status, which dates to update, and which (optional) properties receive tracking data. Property names are yours; nothing in the code assumes a particular schema.
2. You define a sequence: "rows with status Ready get `initial.txt`, then move to Contacted with a next action in 7 days", and so on.
3. `notion-chimp run` finds rows that are due, renders each template with that row's properties, and shows you what it would send. `--send` sends them through Gmail (or SMTP) and advances each row.
4. Each HTML email carries a tracking pixel and wrapped links pointing at your tracking server. When the recipient opens the email or clicks a link, the server writes to that row: open count, first opened, link clicked, last engagement.

```
Notion DB ──> notion-chimp run ──> Gmail ──> recipient
    ^                                           │
    └──────── tracking server <── pixel / click ┘
```

## Install

Python 3.10+.

```bash
git clone https://github.com/erikdohnberg/notion-chimp.git
cd notion-chimp
python -m venv .venv && source .venv/bin/activate
pip install -e '.[gmail]'
cp .env.example .env
notion-chimp gen-key          # paste the output into NOTION_CHIMP_SECRET_KEY in .env
```

Keep `NOTION_CHIMP_SECRET_KEY` stable. Tracking links are encrypted with it, so changing it breaks every link you've already sent.

## Notion setup

1. Create an integration. In Notion, go to Settings, then Connections, then "Develop or manage integrations", and create a new internal integration for your workspace. It needs "Read content" and "Update content". It does not need "Insert content" or any user information.
2. Copy the integration secret into `NOTION_TOKEN` in `.env`.
3. Share the database with the integration. Open the database page, use the `•••` menu, choose Connections, and add your integration. Without this step every API call returns 404.
4. Get the data source URL. Open the database, use "Copy link" or look under "Manage data sources" for a `collection://...` URL. A regular database URL also works if the database has a single data source.
5. Add the tracking properties you want, by hand. notion-chimp never creates, renames or deletes properties. Suggested types:

| Role | Suggested type |
| --- | --- |
| open_count | Number |
| first_opened | Date |
| link_clicked | Checkbox, or Date if you want to know when |
| last_engagement | Date |

Any of these can be left out of the config and notion-chimp will skip it.

Then check your config against the live database:

```bash
notion-chimp -c my-config.yaml check
```

`check` confirms every mapped property exists with a compatible type, that each step's statuses are real options, and that every `{placeholder}` in your templates is a property. It changes nothing.

## Configuration

Start from [`examples/mogul-mania/config.yaml`](examples/mogul-mania/config.yaml). It is a working setup for event sponsor outreach and is commented line by line. The parts that matter:

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
Subject: Sponsoring Mogul Mania 2027 – {Company}

Hi {Contact Name|there},

The sponsor package is here: [Sponsor package](https://example.com/package.pdf)
```

`{Property Name}` inserts that property's value. `{Property Name|fallback}` uses the fallback when the row is empty; without a fallback an empty value skips the row rather than sending "Hi ,". Links can be bare URLs or `[text](url)`. Each email goes out as plain text plus HTML, and only the HTML part is tracked.

## Gmail setup

notion-chimp asks only for the `gmail.send` scope. It can send as you; it cannot read your mail.

1. In Google Cloud Console, create a project and enable the Gmail API.
2. Configure the OAuth consent screen (External is fine for a personal account) and add your own address as a test user.
3. Create an OAuth client ID of type "Desktop app" and download the JSON as `credentials.json` in the project folder.
4. Run `notion-chimp -c my-config.yaml auth-gmail`. A browser opens for consent and `token.json` is saved. Both files are gitignored.

While the consent screen is in "Testing" status, Google expires the refresh token after 7 days, so you'll need to rerun `auth-gmail` weekly. Publishing the app (it can stay unverified for personal use) removes that limit.

To send through another provider, set `sender.provider: smtp` and the `SMTP_*` variables. Adding a provider means writing a class with a `send(email) -> message_id` method and registering it in `notion_chimp/senders/__init__.py`. The tracking core never sees which sender was used.

## Running a campaign

```bash
notion-chimp -c my-config.yaml run              # dry run: lists what would send
notion-chimp -c my-config.yaml run --send       # send and update rows
notion-chimp -c my-config.yaml run --send --limit 5
```

Dry run is the default. Run it daily (cron, a scheduled GitHub Action, whatever you have) to work through follow-ups as they come due. If a send succeeds but the Notion update fails, the output says so and names the row; fix that row by hand or the next run will send it again.

## The tracking server

The server has two routes:

- `GET /o/<token>.gif` returns a 1x1 transparent GIF and records an open.
- `GET /c/<token>` redirects to the original link and records a click.

Tokens are encrypted with your secret key, so recipients can't see row ids and nobody can use your server as an open redirect. Recipients always get their image or their redirect, even when a hit is filtered, the kill switch is on, or Notion is unreachable. Only the write-back is skipped. `GET /healthz` reports whether the kill switch is on.

Run it locally with `notion-chimp -c my-config.yaml serve`. In production, put it behind HTTPS on a domain you control and run it with gunicorn:

```bash
pip install '.[server]'
NOTION_CHIMP_CONFIG=my-config.yaml gunicorn -w 2 -b 0.0.0.0:8000 notion_chimp.wsgi:app
```

A `Dockerfile` is included. Set `NOTION_CHIMP_BASE_URL` to the public URL before sending anything, because that URL is baked into every email.

### Deploying to Vercel

The repo root has an `app.py` and `requirements.txt`, so Vercel deploys it as a Flask app with no extra setup. Import the repo (or your fork) as a Vercel project, then set these environment variables in the project settings:

| Variable | Value |
| --- | --- |
| `NOTION_CHIMP_CONFIG_YAML` | The full contents of your config file. This keeps your database id and property names out of the repo. |
| `NOTION_TOKEN` | Your Notion integration secret. Mark it Sensitive. |
| `NOTION_CHIMP_SECRET_KEY` | The same key you use locally for sending. Mark it Sensitive. |
| `NOTION_CHIMP_BASE_URL` | The deployment's production URL, e.g. `https://notion-chimp-you.vercel.app` |

Turn off Vercel Authentication (Settings, Deployment Protection) for production, or every pixel and link will hit a login wall. Visit `/healthz` after deploying; it reports whether the token and key are set without revealing them.

Three differences from a long-running server: writes to Notion happen before the response (Vercel can freeze a function as soon as it responds), the dedupe window is per function instance so a few extra repeat opens may count, and the kill switch file doesn't apply. Flip the kill switch by setting `NOTION_CHIMP_KILL_SWITCH=1` and redeploying.

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

1. Add a test row to the database with a company name you'll recognize, a status matching your first step, and any email address. The address is ignored in step 2.
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

## Example: Mogul Mania sponsor outreach

[`examples/mogul-mania/`](examples/mogul-mania/) is the reference setup. It was built for sponsor outreach for a ski club's mogul competition: each row is a local business, the sequence is an initial email and two follow-ups a week apart, and the tracked link is the sponsor package. To adapt it, copy the folder, point `data_source` at your database, rename the properties on the right-hand side to match yours, and rewrite the templates. If your statuses are different, change `when_status` and `set_status` to match.

## License

MIT. See [LICENSE](LICENSE).
