# GCC Email Notification Monitor

This project checks the official Gauhati Commerce College notification pages and emails new PDF-linked notices to your inbox. Each email includes:
- the notification title and category;
- the direct PDF URL and notice page URL;
- the actual PDF as an attachment.

It uses Python, GitHub Actions, and Gmail SMTP. The intended setup can run at no hosting cost on a **public GitHub repository**, subject to GitHub/Gmail limits and policy changes. The code is public; keep all credentials in GitHub Actions Secrets only.

## Important first-run behaviour

The first run creates a baseline of notices already on the site and does **not** email old notices. Subsequent runs email new PDF-linked notices only. If the college changes its page structure, check the Actions log because a scraper can miss notices until updated.

## Setup

### 1. Create a GitHub repository
1. Sign in to GitHub and create a new repository named `gcc-email-notifier`.
2. Set it to **Public** to use GitHub-hosted Actions without consuming private-repository minutes. The source code will be public, but your email credentials are stored separately as repository secrets.
3. Upload all files from this project, including the `.github/workflows/check-gcc.yml` file, preserving the folder structure.
4. In the repository, open **Settings → Actions → General → Workflow permissions** and allow read and write permissions if your repository settings require it.

### 2. Prepare Gmail securely
1. Use the Gmail account where you want to receive notices. If you want another inbox, you can set that separately in `RECIPIENT_EMAIL`.
2. Turn on 2-Step Verification in your Google Account.
3. Create an **App Password** from Google's App Passwords page, if the feature is available to your account. Do not use your normal Gmail password.
4. Never put the app password into the code, a public file, or a chat message.

Google help: https://support.google.com/mail/answer/185833

### 3. Add repository secrets
Open **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret name | Value |
|---|---|
| `GMAIL_ADDRESS` | The Gmail account used to send the emails |
| `GMAIL_APP_PASSWORD` | The 16-character Google app password |
| `RECIPIENT_EMAIL` | Your receiving email address (can be the same Gmail address) |

### 4. Run a test
1. Open **Actions → Check GCC notifications**.
2. Click **Run workflow**.
3. On the first successful run, the monitor saves the current notice list as a baseline and sends no old notices.
4. Open the workflow run and inspect its log. It should show the number of PDF-linked notices found for each category and say `Baseline initialized`.
5. Run it a second time to test the workflow. It should not send duplicates.
6. Future scheduled runs check every 15 minutes. GitHub may delay scheduled workflows during high load; this is not an exact-time guarantee.

## Notes
- The monitor covers the official General Notifications, Admission, Recruitments, Tenders, and Examinations category pages configured in `monitor.py`.
- Only notices with a discoverable PDF link are emailed. Notices without a PDF are skipped.
- The script limits PDF attachments to 20 MB and checks that the download looks like a PDF.
- If Gmail changes security requirements or an account cannot create app passwords, use a different authenticated email method rather than sharing your main password.
- This is a personal-use monitor. Please keep requests reasonable and do not run it more frequently than needed.
