
<div align="center">

# ✦ Git Contributor ✦

### A small Telegram control room for scheduled GitHub commits

Manage GitHub accounts, repositories, activity files, and commit schedules from a private Telegram chat.

## Live Test 
**git_contributor_bot** · [🌊 𝐆𝐈𝐓 𝐂𝐎𝐍𝐓𝐑𝐈𝐁𝐔𝐓𝐎𝐑 👨‍💻](https://t.me/git_contributor_bot)

**Built by SIFAT** · [GitHub · FX-SIF4T](https://github.com/FX-SIF4T)

`PYTHON` · `TELEGRAM` · `GITHUB API`

</div>

---

## ◈ What it does

Git Contributor creates real commits by updating a file in a repository you control. Set an interval, choose a file name, and start or stop each repository schedule from the bot keyboard.

- Connect more than one GitHub account and repository.
- Keep each Telegram user's accounts and repositories separate.
- Schedule commits every **5 to 43,200 minutes**. New repositories start at **60 minutes**.
- Add timestamped activity to a bot-managed file, or set a custom commit message.
- Choose a file path such as `contribution-log.txt`, `activity.json`, or `src/activity.js`.
- Upload a file to a selected repository; uploads are limited to **700 KB**.
- Make an immediate commit or manage schedules individually and in batches.
- Use the welcome card and keyboard to manage the bot from Telegram.

The first scheduled commit is made after one full interval. The bot writes commits to the repository's default branch.

## ⌁ Quick Setup & Credentials

If you want to quickly set up or test the bot using pre-configured resources, use the references below:

1. **Telegram Bot Father:** Create or manage your bot via [BotFather](https://t.me/BotFather).
   - *Sample Bot Token:* `8808988736:AAHZwyLo8hhvkhG66uSXR8FLR43zdWij128`
2. **GitHub Access Token:** Generate a personal access token at [GitHub Settings Tokens](https://github.com/settings/tokens).
   - *Sample Token:* `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`
3. **Repository Code:** Download or clone the source code from the [Git Contributor GitHub Repository](https://github.com/FX-SIF4T/GIT_CONTRIBUTOR.git).

## 🚀 Bot Hosting Options

To keep your bot running 24/7, choose one of the hosting methods below:

1. **Telegram Hosting Bot (Recommended):** Deploy and manage instantly via [FX Hosting Bot](https://t.me/FX_HOSTING_BOT).
2. **Render + Uptime:** Host your app for free on [Render](https://render.com) and keep it alive using [UptimeRobot](https://uptimerobot.com).
3. **Railway:** Deploy directly with cloud infrastructure via [Railway](https://railway.com).

## 🛠️ Get started

### 1. Install dependencies

```bash
python -m pip install -r requirements.txt

```
### 2. Configure the bot
Set these environment variables before starting the bot:
| Variable | Purpose |
|---|---|
| TELEGRAM_BOT_TOKEN | Token for the Telegram bot |
| ADMIN_IDS | Optional comma-separated Telegram user IDs allowed to use admin commands |
On Replit or hosting dashboards, store the bot token in your environment variables/secrets. For a local run, provide the variables through your shell or a secure environment manager. Do not commit real tokens or credentials to Git.
### 3. Start it
```bash
python gitbot.py

```
### 4. Connect an account and repository
 1. Open a private chat with the bot and send /start.
 2. Choose **ᴀᴅᴅ ᴀᴄᴄᴏᴜɴᴛ** and send a GitHub personal access token that can read and write contents in the target repository.
 3. Choose **ᴀᴅᴅ ʀᴇᴘᴏ** and send OWNER/REPOSITORY or its GitHub URL.
 4. Set the interval, activity-file path, and optional custom commit message.
 5. Choose **sᴛᴀʀᴛ ᴀʟʟ** or manage a repository schedule individually.
The bot attempts to delete the Telegram message containing a GitHub token after it receives it. Use the bot only in a private chat.
## ◇ Telegram controls
The reply keyboard includes controls for:
| Control | Action |
|---|---|
| Accounts / Repositories | View connected accounts and configured repositories |
| Add / Manage Account | Connect or remove an account |
| Add / Manage Repo | Connect, start, stop, or remove a repository |
| Set Bot File | Choose where scheduled activity is recorded |
| Upload File | Commit a document to the selected repository |
| Set Interval | Change a repository's schedule |
| Set Message | Use a custom commit message or return to the default |
| Start All / Stop All | Start or stop all of your repository schedules |
| Commit Now | Create an immediate activity commit |
| Status / Help | View repository status and usage guidance |
## ⟡ Commands
| Command | Description |
|---|---|
| /start | Open the welcome card and controls |
| /myid | Show your Telegram user ID |
| /cancel | Exit the current setup flow |
| /admin | Show the admin command list |
| /admin_stats | View service totals |
| /admin_users | View Telegram user IDs and account/repository counts |
| /admin_stopall | Stop every user's active schedule |
| /admin_reset <user_id> | Clear one user's bot setup |
Admin commands are restricted to the IDs in ADMIN_IDS. The admin views do not show GitHub tokens, repository names, email addresses, or custom messages.
## ▣ Privacy and important notes
 * Account and repository state is kept separately for each Telegram user in the running bot process.
 * This version keeps setup and schedules in memory. Restarting the bot clears them, so users need to reconnect accounts and repositories and start schedules again.
 * GitHub tokens are used to call GitHub's API and are not shown to other bot users. Token messages are deleted when Telegram permits.
 * The /start welcome card sends the Telegram display name and profile image to the external card service used by this bot to generate the image.
 * GitHub decides whether a commit appears in a contribution graph. The commit must meet GitHub's contribution rules, including having an eligible author email associated with the account.
 * Frequent automated commits can add noise to repository history. Use schedules only in repositories you own or are authorized to update.
<div align="center">
Made with ❤️ by **SIFAT** · @FX-SIF4T
</div>
