import ast
import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse

import httpx
from telegram import ReplyKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


API_ROOT = "https://api.github.com"
DEFAULT_FILE_PATH = "contribution-log.txt"
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 43200
MAX_LOG_LINES = 1000
MAX_UPLOAD_BYTES = 700_000
HARDCODED_TELEGRAM_BOT_TOKEN = ""
HARDCODED_ADMIN_IDS: set[int] = set()

BUTTON_ACCOUNTS = "ᴀᴄᴄᴏᴜɴᴛs"
BUTTON_REPOSITORIES = "ʀᴇᴘᴏsɪᴛᴏʀɪᴇs"
BUTTON_ADD_ACCOUNT = "ᴀᴅᴅ ᴀᴄᴄᴏᴜɴᴛ"
BUTTON_ADD_REPOSITORY = "ᴀᴅᴅ ʀᴇᴘᴏ"
BUTTON_MANAGE_ACCOUNT = "ᴍᴀɴᴀɢᴇ ᴀᴄᴄᴏᴜɴᴛ"
BUTTON_MANAGE_REPOSITORY = "ᴍᴀɴᴀɢᴇ ʀᴇᴘᴏ"
BUTTON_FILE_PATH = "sᴇᴛ ʙᴏᴛ ғɪʟᴇ"
BUTTON_UPLOAD_FILE = "ᴜᴘʟᴏᴀᴅ ғɪʟᴇ"
BUTTON_INTERVAL = "sᴇᴛ ɪɴᴛᴇʀᴠᴀʟ"
BUTTON_MESSAGE = "sᴇᴛ ᴍᴇssᴀɢᴇ"
BUTTON_START_ALL = "sᴛᴀʀᴛ ᴀʟʟ"
BUTTON_STOP_ALL = "sᴛᴏᴘ ᴀʟʟ"
BUTTON_COMMIT_NOW = "ᴄᴏᴍᴍɪᴛ ɴᴏᴡ"
BUTTON_STATUS = "sᴛᴀᴛᴜs"
BUTTON_HELP = "ʜᴇʟᴘ"

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("gitbot")


@dataclass
class GitHubAccount:
    account_id: str
    login: str
    author_name: str
    author_email: str = field(repr=False)
    token: str = field(repr=False)


@dataclass
class RepoSchedule:
    repo_id: str
    account_id: str
    repository: str
    branch: str
    interval_minutes: int = 60
    file_path: str = DEFAULT_FILE_PATH
    message_mode: str = "default"
    custom_message: str = ""
    last_commit: str = "ɴᴏɴᴇ"
    last_error: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)
    commit_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


@dataclass
class UserState:
    accounts: dict[str, GitHubAccount] = field(default_factory=dict)
    repositories: dict[str, RepoSchedule] = field(default_factory=dict)
    next_account_number: int = 1
    next_repo_number: int = 1


class GitHubError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(str(status_code))


def normalize_management_command(value: str) -> str:
    translation = str.maketrans(
        {
            "ʀ": "r",
            "ᴇ": "e",
            "ᴍ": "m",
            "ᴏ": "o",
            "ᴠ": "v",
            "ᴘ": "p",
            "ᴛ": "t",
            "ᴀ": "a",
        }
    )
    return value.translate(translation).strip().upper()


def get_bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or HARDCODED_TELEGRAM_BOT_TOKEN.strip()


def load_admin_ids() -> set[int]:
    admin_ids = set(HARDCODED_ADMIN_IDS)
    for value in os.getenv("ADMIN_IDS", "8438269386").split(","):
        value = value.strip()
        if not value:
            continue
        if not value.isdecimal() or int(value) <= 0:
            raise SystemExit("ᴀᴅᴍɪɴ_ɪᴅs ᴍᴜsᴛ ʙᴇ ᴄᴏᴍᴍᴀ-sᴇᴘᴀʀᴀᴛᴇᴅ ᴘᴏsɪᴛɪᴠᴇ ᴛᴇʟᴇɢʀᴀᴍ ᴜsᴇʀ ɪᴅs.")
        admin_ids.add(int(value))
    return admin_ids


def is_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return bool(user and user.id in context.application.bot_data.get("admin_ids", set()))


async def require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_private(update):
        if update.effective_message:
            await update.effective_message.reply_text("ᴘʟᴇᴀsᴇ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ᴀ ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ.")
        return False
    if not is_admin(update, context):
        if update.effective_message:
            await update.effective_message.reply_text("⟦ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ ⟧")
        return False
    return True


def main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [BUTTON_ACCOUNTS, BUTTON_REPOSITORIES],
        [BUTTON_ADD_ACCOUNT, BUTTON_ADD_REPOSITORY],
        [BUTTON_MANAGE_ACCOUNT, BUTTON_MANAGE_REPOSITORY],
        [BUTTON_FILE_PATH, BUTTON_UPLOAD_FILE],
        [BUTTON_INTERVAL, BUTTON_MESSAGE],
        [BUTTON_START_ALL, BUTTON_STOP_ALL],
        [BUTTON_COMMIT_NOW, BUTTON_STATUS],
        [BUTTON_HELP],
    ]
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="ᴄʜᴏᴏsᴇ ᴀ ᴄᴏɴᴛʀᴏʟ",
    )


async def send_panel(update: Update, text: str) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=main_keyboard())


async def send_to_user(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str) -> None:
    await context.bot.send_message(user_id, text, reply_markup=main_keyboard())


async def delete_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    try:
        await context.bot.delete_message(
            chat_id=message.chat_id,
            message_id=message.message_id,
        )
    except Exception:
        logger.info("A sensitive setup message could not be deleted")


def get_user_state(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> UserState:
    return context.application.bot_data["users"].setdefault(user_id, UserState())


def clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "flow_step",
        "selected_account_id",
        "selected_repo_id",
    ):
        context.user_data.pop(key, None)


def parse_repository(value: str) -> str | None:
    value = value.strip()
    if value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            return None
        value = parsed.path.strip("/")
        if value.endswith(".git"):
            value = value[:-4]
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", value)
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def normalize_file_path(value: str) -> str | None:
    raw = value.strip().replace("\\", "/")
    parts = raw.split("/")
    if (
        not raw
        or len(raw) > 240
        or raw.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0].lower() == ".git"
        or any(ord(character) < 32 for character in raw)
    ):
        return None
    return raw


async def github_request(
    token: str,
    method: str,
    path: str,
    payload: dict | None = None,
    params: dict | None = None,
) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.request(
            method,
            f"{API_ROOT}{path}",
            headers=headers,
            json=payload,
            params=params,
        )
    if response.status_code >= 400:
        raise GitHubError(response.status_code)
    if not response.content:
        return {}
    return response.json()


async def get_author_identity(token: str, profile: dict) -> tuple[str, str]:
    name = profile.get("name") or profile.get("login") or "GitHub contributor"
    try:
        emails = await github_request(token, "GET", "/user/emails")
        for item in emails if isinstance(emails, list) else []:
            if item.get("primary") and item.get("verified") and item.get("email"):
                return name, item["email"]
    except GitHubError:
        pass
    if profile.get("email"):
        return name, profile["email"]
    login = profile.get("login", "contributor")
    user_id = profile.get("id")
    if user_id:
        return name, f"{user_id}+{login}@users.noreply.github.com"
    return name, f"{login}@users.noreply.github.com"


async def validate_repository(token: str, repository: str) -> dict:
    repo_data = await github_request(token, "GET", f"/repos/{repository}")
    if (repo_data.get("permissions") or {}).get("push") is False:
        raise GitHubError(403)
    return repo_data


def activity_content(file_path: str, existing: bytes, entry: str) -> bytes:
    extension = PurePosixPath(file_path).suffix.lower()
    text = existing.decode("utf-8", errors="strict") if existing else ""

    if extension == ".json":
        data = json.loads(text) if text else {}
        if isinstance(data, dict):
            entries = data.get("_gitbot_activity", [])
            if not isinstance(entries, list):
                raise ValueError("json activity field is not a list")
            entries.append(entry)
            data["_gitbot_activity"] = entries[-MAX_LOG_LINES:]
        else:
            data = {"_gitbot_original": data, "_gitbot_activity": [entry]}
        return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    if extension in {".js", ".mjs", ".cjs", ".ts"}:
        if extension == ".ts":
            pattern = r"const gitbotActivity: string\[\] = (\[.*\]);\s*"
        else:
            pattern = r"const gitbotActivity = (\[.*\]);\s*"
        match = re.fullmatch(pattern, text, flags=re.DOTALL) if text else None
        if text and not match:
            raise ValueError("existing script is not a bot-generated activity file")
        entries = json.loads(match.group(1)) if match else []
        if not isinstance(entries, list):
            raise ValueError("script activity data is invalid")
        entries.append(entry)
        encoded = json.dumps(entries[-MAX_LOG_LINES:], ensure_ascii=False, indent=2)
        declaration = "const gitbotActivity: string[]" if extension == ".ts" else "const gitbotActivity"
        return f"{declaration} = {encoded};\n".encode("utf-8")

    if extension == ".py":
        match = re.fullmatch(r"gitbot_activity = (.*)\s*", text, flags=re.DOTALL) if text else None
        if text and not match:
            raise ValueError("existing script is not a bot-generated activity file")
        entries = ast.literal_eval(match.group(1)) if match else []
        if not isinstance(entries, list):
            raise ValueError("python activity data is invalid")
        entries.append(entry)
        return f"gitbot_activity = {entries[-MAX_LOG_LINES:]!r}\n".encode("utf-8")

    lines = [line for line in text.splitlines() if line.strip()]
    lines.append(entry)
    return ("\n".join(lines[-MAX_LOG_LINES:]) + "\n").encode("utf-8")


def repo_contents_endpoint(target: RepoSchedule, file_path: str | None = None) -> str:
    path = quote(file_path or target.file_path, safe="/")
    return f"/repos/{target.repository}/contents/{path}"


async def get_remote_file(
    account: GitHubAccount,
    target: RepoSchedule,
    file_path: str | None = None,
) -> tuple[str | None, bytes]:
    try:
        result = await github_request(
            account.token,
            "GET",
            repo_contents_endpoint(target, file_path),
            params={"ref": target.branch},
        )
    except GitHubError as error:
        if error.status_code == 404:
            return None, b""
        raise
    encoded = re.sub(r"\s+", "", result.get("content", ""))
    content = base64.b64decode(encoded) if encoded else b""
    return result.get("sha"), content


async def put_repository_file(
    account: GitHubAccount,
    target: RepoSchedule,
    file_path: str,
    content: bytes,
    commit_message: str,
    timestamp: datetime,
) -> str:
    file_sha, _ = await get_remote_file(account, target, file_path)
    payload = {
        "message": commit_message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": target.branch,
        "author": {
            "name": account.author_name,
            "email": account.author_email,
            "date": timestamp.isoformat(),
        },
        "committer": {
            "name": account.author_name,
            "email": account.author_email,
            "date": timestamp.isoformat(),
        },
    }
    if file_sha:
        payload["sha"] = file_sha
    result = await github_request(
        account.token,
        "PUT",
        repo_contents_endpoint(target, file_path),
        payload=payload,
    )
    return result.get("commit", {}).get("sha", "")[:12] or timestamp.strftime("%Y-%m-%d")


async def create_activity_commit(account: GitHubAccount, target: RepoSchedule) -> str:
    async with target.commit_lock:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S ᴜᴛᴄ")
        if target.message_mode == "custom" and target.custom_message:
            commit_message = target.custom_message
            entry_message = target.custom_message.replace("\n", " ")
        else:
            commit_message = f"ᴄᴏɴᴛʀɪʙᴜᴛɪᴏɴ ᴜᴘᴅᴀᴛᴇ · {now.strftime('%Y-%m-%d %H:%M ᴜᴛᴄ')}"
            entry_message = "ᴅᴀɪʟʏ ᴄᴏɴᴛʀɪʙᴜᴛɪᴏɴ"
        entry = f"{timestamp} | {entry_message}"
        file_sha, previous = await get_remote_file(account, target)
        content = activity_content(target.file_path, previous, entry)
        payload = {
            "message": commit_message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": target.branch,
            "author": {
                "name": account.author_name,
                "email": account.author_email,
                "date": now.isoformat(),
            },
            "committer": {
                "name": account.author_name,
                "email": account.author_email,
                "date": now.isoformat(),
            },
        }
        if file_sha:
            payload["sha"] = file_sha
        result = await github_request(
            account.token,
            "PUT",
            repo_contents_endpoint(target),
            payload=payload,
        )
        return result.get("commit", {}).get("sha", "")[:12] or timestamp


async def create_uploaded_commit(
    account: GitHubAccount,
    target: RepoSchedule,
    file_path: str,
    content: bytes,
) -> str:
    async with target.commit_lock:
        now = datetime.now(timezone.utc)
        short_name = PurePosixPath(file_path).name[:80]
        message = f"ғɪʟᴇ ᴜᴘʟᴏᴀᴅ · {short_name} · {now.strftime('%Y-%m-%d %H:%M ᴜᴛᴄ')}"
        return await put_repository_file(account, target, file_path, content, message, now)


async def schedule_loop(
    user_id: int,
    repo_id: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    try:
        while True:
            state: UserState | None = context.application.bot_data["users"].get(user_id)
            target = state.repositories.get(repo_id) if state else None
            if not target:
                return
            await asyncio.sleep(target.interval_minutes * 60)
            account = state.accounts.get(target.account_id)
            if not account:
                target.last_error = "ᴀᴄᴄᴏᴜɴᴛ ɴᴏᴛ ғᴏᴜɴᴅ"
                return
            try:
                target.last_commit = await create_activity_commit(account, target)
                target.last_error = ""
            except GitHubError as error:
                target.last_error = f"ɢɪᴛʜᴜʙ ʀᴇǫᴜᴇsᴛ ғᴀɪʟᴇᴅ · {error.status_code}"
                await send_to_user(context, user_id, f"⟦ {repo_id} · {target.last_error} ⟧")
            except (httpx.HTTPError, ValueError, UnicodeError, json.JSONDecodeError):
                target.last_error = "ғɪʟᴇ ᴏʀ ɴᴇᴛᴡᴏʀᴋ ᴇʀʀᴏʀ · ᴄʜᴇᴄᴋ ᴛʜᴇ ᴘᴀᴛʜ ᴀɴᴅ ғɪʟᴇ ғᴏʀᴍᴀᴛ"
                await send_to_user(context, user_id, f"⟦ {repo_id} · {target.last_error} ⟧")
    except asyncio.CancelledError:
        raise


def start_schedule(
    user_id: int,
    target: RepoSchedule,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    if target.task and not target.task.done():
        return False
    target.task = asyncio.create_task(schedule_loop(user_id, target.repo_id, context))
    return True


def stop_schedule(target: RepoSchedule) -> bool:
    if not target.task or target.task.done():
        target.task = None
        return False
    target.task.cancel()
    target.task = None
    return True


def find_account(state: UserState, account_id: str) -> GitHubAccount | None:
    key = account_id.strip().upper()
    return next((account for account in state.accounts.values() if account.account_id == key), None)


def find_repository(state: UserState, repo_id: str) -> RepoSchedule | None:
    key = repo_id.strip().upper()
    return next((target for target in state.repositories.values() if target.repo_id == key), None)


def render_account_list(state: UserState) -> str:
    if not state.accounts:
        return "⟦ ɢɪᴛʜᴜʙ ᴀᴄᴄᴏᴜɴᴛs ⟧\n\nɴᴏ ᴀᴄᴄᴏᴜɴᴛs ᴀᴅᴅᴇᴅ"
    lines = ["⟦ ɢɪᴛʜᴜʙ ᴀᴄᴄᴏᴜɴᴛs ⟧"]
    for account in state.accounts.values():
        repo_count = sum(1 for target in state.repositories.values() if target.account_id == account.account_id)
        lines.append(f"{account.account_id} · {account.login} · {repo_count} ʀᴇᴘᴏs")
    return "\n".join(lines)[:3800]


def render_repository_list(state: UserState) -> str:
    if not state.repositories:
        return "⟦ ʀᴇᴘᴏsɪᴛᴏʀɪᴇs ⟧\n\nɴᴏ ʀᴇᴘᴏsɪᴛᴏʀɪᴇs ᴀᴅᴅᴇᴅ"
    lines = ["⟦ ʀᴇᴘᴏsɪᴛᴏʀɪᴇs · sᴄʜᴇᴅᴜʟᴇs ⟧"]
    for target in state.repositories.values():
        account = state.accounts.get(target.account_id)
        owner = account.login if account else "ᴜɴʟɪɴᴋᴇᴅ"
        active = bool(target.task and not target.task.done())
        status = "ᴀᴄᴛɪᴠᴇ" if active else "sᴛᴏᴘᴘᴇᴅ"
        mode = "ᴄᴜsᴛᴏᴍ" if target.message_mode == "custom" else "ᴅᴇғᴀᴜʟᴛ"
        lines.append(
            f"{target.repo_id} · {target.repository}\n"
            f"ᴀᴄᴄᴏᴜɴᴛ · {target.account_id}/{owner}\n"
            f"ғɪʟᴇ · {target.file_path}\n"
            f"ɪɴᴛᴇʀᴠᴀʟ · {target.interval_minutes} ᴍɪɴ · {mode} · {status}\n"
            f"ʟᴀsᴛ ᴄᴏᴍᴍɪᴛ · {target.last_commit}"
        )
    return "\n\n".join(lines)[:3800]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_private(update):
        await update.effective_message.reply_text("ᴘʟᴇᴀsᴇ ᴜsᴇ ᴛʜɪs ʙᴏᴛ ɪɴ ᴀ ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ.")
        return
    clear_flow(context)
    state = get_user_state(context, update.effective_user.id)
    user = update.effective_user
    display_name = (user.full_name or user.username or "ᴠɪsɪᴛᴏʀ").strip()[:64]
    welcome_message = (
        "╭── [ ᴡᴇʟᴄᴏᴍᴇ ]\n"
        "│\n"
        f"├── ɴᴀᴍᴇ · {display_name}\n"
        "├── sᴇʀᴠɪᴄᴇ · ɢɪᴛ ᴄᴏɴᴛʀɪʙᴜᴛɪᴏɴ ᴄᴏɴsᴏʟᴇ\n"
        f"├── ɢɪᴛʜᴜʙ ᴀᴄᴄᴏᴜɴᴛs · {len(state.accounts)}\n"
        f"├── ʀᴇᴘᴏsɪᴛᴏʀɪᴇs · {len(state.repositories)}\n"
        "│\n"
        "├── ᴜsᴇ ᴛʜᴇ ᴋᴇʏʙᴏᴀʀᴅ ᴛᴏ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ sᴇᴛᴜᴘ\n"
        "╰── ᴘᴏᴡᴇʀᴇᴅ ʙʏ sɪғᴜ"
    )
    try:
        profile_photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if not profile_photos.photos or not profile_photos.photos[0]:
            raise ValueError("profile photo unavailable")
        smallest_photo = profile_photos.photos[0][0]
        telegram_file = await context.bot.get_file(smallest_photo.file_id)
        avatar_bytes = bytes(await telegram_file.download_as_bytearray())
        if not avatar_bytes or len(avatar_bytes) > 5000:
            raise ValueError("profile photo cannot fit in the card request")
        avatar = "data:image/jpeg;base64," + base64.b64encode(avatar_bytes).decode("ascii")
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            response = await client.get(
                "https://maybexenos.vercel.app/welcome-card/greetings",
                params={
                    "avatar": avatar,
                    "username": display_name.upper(),
                    "type": "welcome",
                    "bg": "https://i.imgur.com/enLKVSZ.jpeg",
                },
            )
            response.raise_for_status()
        if not response.headers.get("content-type", "").startswith("image/"):
            raise ValueError("welcome card response is not an image")
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=response.content,
            caption=welcome_message,
            reply_markup=main_keyboard(),
        )
    except Exception as error:
        logger.warning("Welcome card unavailable: %s", type(error).__name__)
        await send_panel(update, welcome_message)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_private(update):
        await update.effective_message.reply_text("ᴘʟᴇᴀsᴇ ᴜsᴇ ᴛʜɪs ʙᴏᴛ ɪɴ ᴀ ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ.")
        return
    clear_flow(context)
    await send_panel(update, "⟦ ᴄᴜʀʀᴇɴᴛ ᴀᴄᴛɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ ⟧")


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_private(update):
        await update.effective_message.reply_text("ᴘʟᴇᴀsᴇ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ᴀ ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ.")
        return
    await update.effective_message.reply_text(
        f"⟦ ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴍ ᴜsᴇʀ ɪᴅ · {update.effective_user.id} ⟧",
        reply_markup=main_keyboard(),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    await update.effective_message.reply_text(
        "⟦ ᴀᴅᴍɪɴ ᴄᴏɴsᴏʟᴇ ⟧\n\n"
        "/admin_stats · sᴇʀᴠɪᴄᴇ ᴄᴏᴜɴᴛs\n"
        "/admin_users · ᴜsᴇʀ ɪᴅ ᴀɴᴅ ᴄᴏᴜɴᴛs ᴏɴʟʏ\n"
        "/admin_stopall · sᴛᴏᴘ ᴀʟʟ sᴄʜᴇᴅᴜʟᴇs\n"
        "/admin_reset <user_id> · ᴄʟᴇᴀʀ ᴏɴᴇ ᴜsᴇʀ\n\n"
        "ɢɪᴛʜᴜʙ ᴛᴏᴋᴇɴs, ʀᴇᴘᴏsɪᴛᴏʀɪᴇs, ᴇᴍᴀɪʟs, ᴀɴᴅ ᴍᴇssᴀɢᴇs ᴀʀᴇ ɴᴏᴛ sʜᴏᴡɴ."
    )


async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    users: dict[int, UserState] = context.application.bot_data["users"]
    accounts = sum(len(state.accounts) for state in users.values())
    repositories = sum(len(state.repositories) for state in users.values())
    running = sum(
        1
        for state in users.values()
        for target in state.repositories.values()
        if target.task and not target.task.done()
    )
    await update.effective_message.reply_text(
        "⟦ ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs ⟧\n\n"
        f"ᴜsᴇʀs · {len(users)}\nᴀᴄᴄᴏᴜɴᴛs · {accounts}\n"
        f"ʀᴇᴘᴏsɪᴛᴏʀɪᴇs · {repositories}\nᴀᴄᴛɪᴠᴇ sᴄʜᴇᴅᴜʟᴇs · {running}",
        reply_markup=main_keyboard(),
    )


async def admin_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    users: dict[int, UserState] = context.application.bot_data["users"]
    lines = ["⟦ ᴜsᴇʀs · ɪᴅ ᴀɴᴅ ᴄᴏᴜɴᴛs ⟧"]
    for user_id, state in sorted(users.items()):
        running = sum(
            1 for target in state.repositories.values()
            if target.task and not target.task.done()
        )
        line = f"{user_id} · ᴀ{len(state.accounts)} · ʀ{len(state.repositories)} · ᴀᴄᴛɪᴠᴇ {running}"
        if sum(len(item) + 1 for item in lines) + len(line) > 3800:
            lines.append("…")
            break
        lines.append(line)
    if len(lines) == 1:
        lines.append("ɴᴏ ᴜsᴇʀs")
    await update.effective_message.reply_text(
        "\n".join(lines),
        reply_markup=main_keyboard(),
    )


async def admin_stopall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    users: dict[int, UserState] = context.application.bot_data["users"]
    stopped = sum(
        1
        for state in users.values()
        for target in state.repositories.values()
        if stop_schedule(target)
    )
    await update.effective_message.reply_text(
        f"⟦ ᴀʟʟ sᴄʜᴇᴅᴜʟᴇs sᴛᴏᴘᴘᴇᴅ · {stopped} ⟧",
        reply_markup=main_keyboard(),
    )


async def admin_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    if len(context.args) != 1 or not context.args[0].isdecimal():
        await update.effective_message.reply_text(
            "⟦ ᴜsᴇ · /admin_reset <user_id> ⟧",
            reply_markup=main_keyboard(),
        )
        return
    target_id = int(context.args[0])
    users: dict[int, UserState] = context.application.bot_data["users"]
    state = users.pop(target_id, None)
    if state:
        for target in state.repositories.values():
            stop_schedule(target)
    user_data = context.application.user_data.get(target_id)
    if user_data is not None:
        user_data.clear()
    if state is None:
        await update.effective_message.reply_text(
            "⟦ ᴜsᴇʀ ɴᴏᴛ ғᴏᴜɴᴅ ⟧",
            reply_markup=main_keyboard(),
        )
        return
    await update.effective_message.reply_text(
        f"⟦ ᴜsᴇʀ sᴇᴛᴜᴘ ᴄʟᴇᴀʀᴇᴅ · {target_id} ⟧",
        reply_markup=main_keyboard(),
    )


async def handle_menu_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
) -> None:
    user_id = update.effective_user.id
    state = get_user_state(context, user_id)

    if action == BUTTON_ACCOUNTS:
        await send_panel(update, render_account_list(state))
    elif action in {BUTTON_REPOSITORIES, BUTTON_STATUS}:
        await send_panel(update, render_repository_list(state))
    elif action == BUTTON_ADD_ACCOUNT:
        context.user_data["flow_step"] = "account_token"
        await send_panel(
            update,
            "⟦ ᴀᴅᴅ ɢɪᴛʜᴜʙ ᴀᴄᴄᴏᴜɴᴛ ⟧\n\n"
            "sᴇɴᴅ ᴀ ɢɪᴛʜᴜʙ ᴘᴇʀsᴏɴᴀʟ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ɪɴ ᴛʜɪs ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ.\n"
            "ɴᴇᴇᴅs ʀᴇᴘᴏsɪᴛᴏʀʏ ᴄᴏɴᴛᴇɴᴛs ʀᴇᴀᴅ ᴀɴᴅ ᴡʀɪᴛᴇ.\n"
            "ᴜsᴇ /cancel ᴛᴏ ᴇxɪᴛ.",
        )
    elif action == BUTTON_ADD_REPOSITORY:
        if not state.accounts:
            await send_panel(update, "⟦ ᴀᴅᴅ ᴀ ɢɪᴛʜᴜʙ ᴀᴄᴄᴏᴜɴᴛ ғɪʀsᴛ ⟧")
            return
        context.user_data["flow_step"] = "repo_account"
        await send_panel(update, render_account_list(state) + "\n\nsᴇɴᴅ ᴛʜᴇ ᴀᴄᴄᴏᴜɴᴛ ɪᴅ ғᴏʀ ᴛʜᴇ ɴᴇᴡ ʀᴇᴘᴏ.")
    elif action == BUTTON_MANAGE_ACCOUNT:
        context.user_data["flow_step"] = "remove_account"
        await send_panel(
            update,
            render_account_list(state)
            + "\n\nᴛᴏ ʀᴇᴍᴏᴠᴇ, sᴇɴᴅ: ʀᴇᴍᴏᴠᴇ a1\nᴀʟʟ ʀᴇᴘᴏ sᴄʜᴇᴅᴜʟᴇs ʟɪɴᴋᴇᴅ ᴛᴏ ɪᴛ ᴡɪʟʟ sᴛᴏᴘ.",
        )
    elif action == BUTTON_MANAGE_REPOSITORY:
        context.user_data["flow_step"] = "manage_repo"
        await send_panel(
            update,
            render_repository_list(state)
            + "\n\nʀᴇᴍᴏᴠᴇ r1 · sᴛᴀʀᴛ r1 · sᴛᴏᴘ r1",
        )
    elif action == BUTTON_FILE_PATH:
        if not state.repositories:
            await send_panel(update, "⟦ ᴀᴅᴅ ᴀ ʀᴇᴘᴏsɪᴛᴏʀʏ ғɪʀsᴛ ⟧")
            return
        context.user_data["flow_step"] = "file_repo"
        await send_panel(update, render_repository_list(state) + "\n\nsᴇɴᴅ ᴛʜᴇ ʀᴇᴘᴏ ɪᴅ ᴛᴏ sᴇᴛ ɪᴛs ʙᴏᴛ ғɪʟᴇ ɴᴀᴍᴇ.")
    elif action == BUTTON_UPLOAD_FILE:
        if not state.repositories:
            await send_panel(update, "⟦ ᴀᴅᴅ ᴀ ʀᴇᴘᴏsɪᴛᴏʀʏ ғɪʀsᴛ ⟧")
            return
        context.user_data["flow_step"] = "upload_repo"
        await send_panel(update, render_repository_list(state) + "\n\nsᴇɴᴅ ᴛʜᴇ ʀᴇᴘᴏ ɪᴅ ғᴏʀ ᴛʜᴇ ғɪʟᴇ ᴜᴘʟᴏᴀᴅ.")
    elif action == BUTTON_INTERVAL:
        if not state.repositories:
            await send_panel(update, "⟦ ᴀᴅᴅ ᴀ ʀᴇᴘᴏsɪᴛᴏʀʏ ғɪʀsᴛ ⟧")
            return
        context.user_data["flow_step"] = "interval_repo"
        await send_panel(update, render_repository_list(state) + "\n\nsᴇɴᴅ ᴛʜᴇ ʀᴇᴘᴏ ɪᴅ ᴛᴏ ᴄʜᴀɴɢᴇ ɪᴛs ɪɴᴛᴇʀᴠᴀʟ.")
    elif action == BUTTON_MESSAGE:
        if not state.repositories:
            await send_panel(update, "⟦ ᴀᴅᴅ ᴀ ʀᴇᴘᴏsɪᴛᴏʀʏ ғɪʀsᴛ ⟧")
            return
        context.user_data["flow_step"] = "message_repo"
        await send_panel(update, render_repository_list(state) + "\n\nsᴇɴᴅ ᴛʜᴇ ʀᴇᴘᴏ ɪᴅ ᴛᴏ ᴄʜᴀɴɢᴇ ɪᴛs ᴄᴏᴍᴍɪᴛ ᴍᴇssᴀɢᴇ.")
    elif action == BUTTON_START_ALL:
        started = sum(start_schedule(user_id, target, context) for target in state.repositories.values())
        await send_panel(update, f"⟦ sᴄʜᴇᴅᴜʟᴇs sᴛᴀʀᴛᴇᴅ · {started} ⟧")
    elif action == BUTTON_STOP_ALL:
        stopped = sum(stop_schedule(target) for target in state.repositories.values())
        await send_panel(update, f"⟦ sᴄʜᴇᴅᴜʟᴇs sᴛᴏᴘᴘᴇᴅ · {stopped} ⟧")
    elif action == BUTTON_COMMIT_NOW:
        if not state.repositories:
            await send_panel(update, "⟦ ᴀᴅᴅ ᴀ ʀᴇᴘᴏsɪᴛᴏʀʏ ғɪʀsᴛ ⟧")
            return
        context.user_data["flow_step"] = "commit_repo"
        await send_panel(update, render_repository_list(state) + "\n\nsᴇɴᴅ ᴛʜᴇ ʀᴇᴘᴏ ɪᴅ ғᴏʀ ᴀɴ ɪᴍᴍᴇᴅɪᴀᴛᴇ ᴄᴏᴍᴍɪᴛ.")
    else:
        await send_panel(
            update,
            "⟦ ᴏᴘᴇʀᴀᴛɪᴏɴ ⟧\n\n"
            "ᴀᴅᴅ ᴀᴄᴄᴏᴜɴᴛs ᴀɴᴅ ʀᴇᴘᴏs, ᴏʀ ᴜsᴇ ᴛʜᴇ ʟɪsᴛ ʙᴜᴛᴛᴏɴs ᴛᴏ ᴍᴀɴᴀɢᴇ ᴛʜᴇᴍ.\n"
            "ᴇᴀᴄʜ ʀᴇᴘᴏ ʜᴀs ɪᴛs ᴏᴡɴ ɪɴᴛᴇʀᴠᴀʟ, ғɪʟᴇ ɴᴀᴍᴇ, ᴀɴᴅ ᴄᴏᴍᴍɪᴛ ᴍᴇssᴀɢᴇ.\n"
            "ᴜᴘʟᴏᴀᴅ ғɪʟᴇ ᴄᴏᴍᴍɪᴛs ɴᴏᴡ; ʙᴏᴛ ғɪʟᴇs ʀᴜɴ ᴏɴ ᴛʜᴇ sᴄʜᴇᴅᴜʟᴇ.\n"
            "ᴜsᴇ /myid ғᴏʀ ʏᴏᴜʀ ᴛᴇʟᴇɢʀᴀᴍ ɪᴅ ᴀɴᴅ /cancel ᴛᴏ ᴇxɪᴛ ᴀ ғʟᴏᴡ.\n"
            "ʏᴏᴜʀ ᴛᴏᴋᴇɴs ᴀɴᴅ ʀᴇᴘᴏ ᴅᴀᴛᴀ ᴀʀᴇ ɪsᴏʟᴀᴛᴇᴅ ᴀɴᴅ ɴᴏᴛ ᴠɪsɪʙʟᴇ ᴛᴏ ᴏᴛʜᴇʀ ᴜsᴇʀs."
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_private(update):
        await update.effective_message.reply_text("ᴘʟᴇᴀsᴇ ᴜsᴇ ᴛʜɪs ʙᴏᴛ ɪɴ ᴀ ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ.")
        return
    message = update.effective_message
    text = message.text.strip()
    user_id = update.effective_user.id
    state = get_user_state(context, user_id)
    step = context.user_data.get("flow_step")
    buttons = {
        BUTTON_ACCOUNTS,
        BUTTON_REPOSITORIES,
        BUTTON_ADD_ACCOUNT,
        BUTTON_ADD_REPOSITORY,
        BUTTON_MANAGE_ACCOUNT,
        BUTTON_MANAGE_REPOSITORY,
        BUTTON_FILE_PATH,
        BUTTON_UPLOAD_FILE,
        BUTTON_INTERVAL,
        BUTTON_MESSAGE,
        BUTTON_START_ALL,
        BUTTON_STOP_ALL,
        BUTTON_COMMIT_NOW,
        BUTTON_STATUS,
        BUTTON_HELP,
    }
    if text in buttons:
        clear_flow(context)
        await handle_menu_action(update, context, text)
        return

    if step == "account_token":
        token = text
        await delete_user_message(update, context)
        try:
            profile = await github_request(token, "GET", "/user")
            author_name, author_email = await get_author_identity(token, profile)
        except GitHubError:
            context.user_data.pop("flow_step", None)
            await send_to_user(context, user_id, "⟦ ᴛᴏᴋᴇɴ ᴠᴀʟɪᴅᴀᴛɪᴏɴ ғᴀɪʟᴇᴅ · ᴛʀʏ ᴀɢᴀɪɴ ⟧")
            return
        except httpx.HTTPError:
            context.user_data.pop("flow_step", None)
            await send_to_user(context, user_id, "⟦ ɴᴇᴛᴡᴏʀᴋ ᴇʀʀᴏʀ · ᴛʀʏ ᴀɢᴀɪɴ ⟧")
            return
        account_id = f"A{state.next_account_number}"
        state.next_account_number += 1
        state.accounts[account_id] = GitHubAccount(
            account_id=account_id,
            login=profile.get("login", "github-user"),
            author_name=author_name,
            author_email=author_email,
            token=token,
        )
        context.user_data.pop("flow_step", None)
        await send_to_user(
            context,
            user_id,
            f"⟦ ɢɪᴛʜᴜʙ ᴀᴄᴄᴏᴜɴᴛ ᴀᴅᴅᴇᴅ · {account_id} · {profile.get('login', 'github-user')} ⟧",
        )
        return

    if step == "repo_account":
        account = find_account(state, text)
        if not account:
            await send_panel(update, "⟦ ᴀᴄᴄᴏᴜɴᴛ ɪᴅ ɴᴏᴛ ғᴏᴜɴᴅ · sᴇɴᴅ ᴀɴ ɪᴅ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ⟧")
            return
        context.user_data["selected_account_id"] = account.account_id
        context.user_data["flow_step"] = "repo_url"
        await send_panel(update, "⟦ ʀᴇᴘᴏsɪᴛᴏʀʏ ⟧\n\nsᴇɴᴅ ᴏᴡɴᴇʀ/ʀᴇᴘᴏ ᴏʀ ᴀ ɢɪᴛʜᴜʙ ᴜʀʟ.")
        return

    if step == "repo_url":
        repository = parse_repository(text)
        account_id = context.user_data.get("selected_account_id", "")
        account = find_account(state, account_id)
        if not repository or not account:
            await send_panel(update, "⟦ ɪɴᴠᴀʟɪᴅ ʀᴇᴘᴏsɪᴛᴏʀʏ ᴏʀ ᴀᴄᴄᴏᴜɴᴛ · ᴛʀʏ ᴀɢᴀɪɴ ⟧")
            return
        if any(target.repository.casefold() == repository.casefold() for target in state.repositories.values()):
            clear_flow(context)
            await send_panel(update, "⟦ ᴛʜɪs ʀᴇᴘᴏsɪᴛᴏʀʏ ɪs ᴀʟʀᴇᴀᴅʏ ᴀᴅᴅᴇᴅ ⟧")
            return
        try:
            repo_data = await validate_repository(account.token, repository)
        except GitHubError as error:
            if error.status_code == 404:
                response = "⟦ ʀᴇᴘᴏsɪᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ᴏʀ ɴᴏ ᴀᴄᴄᴇss ⟧"
            elif error.status_code == 403:
                response = "⟦ ᴛᴏᴋᴇɴ ɴᴇᴇᴅs ᴄᴏɴᴛᴇɴᴛs ʀᴇᴀᴅ ᴀɴᴅ ᴡʀɪᴛᴇ ⟧"
            else:
                response = "⟦ ᴄᴏᴜʟᴅ ɴᴏᴛ ᴠᴀʟɪᴅᴀᴛᴇ ʀᴇᴘᴏsɪᴛᴏʀʏ ⟧"
            await send_panel(update, response)
            return
        except httpx.HTTPError:
            await send_panel(update, "⟦ ɴᴇᴛᴡᴏʀᴋ ᴇʀʀᴏʀ · ᴛʀʏ ᴀɢᴀɪɴ ⟧")
            return
        repo_id = f"R{state.next_repo_number}"
        state.next_repo_number += 1
        state.repositories[repo_id] = RepoSchedule(
            repo_id=repo_id,
            account_id=account.account_id,
            repository=repository,
            branch=repo_data.get("default_branch") or "main",
        )
        clear_flow(context)
        await send_panel(
            update,
            f"⟦ ʀᴇᴘᴏsɪᴛᴏʀʏ ᴀᴅᴅᴇᴅ · {repo_id} · {repository} ⟧\n"
            f"ʙʀᴀɴᴄʜ · {repo_data.get('default_branch') or 'main'}\n"
            f"ʙᴏᴛ ғɪʟᴇ · {DEFAULT_FILE_PATH}\nɪɴɪᴛɪᴀʟ ɪɴᴛᴇʀᴠᴀʟ · 60 ᴍɪɴ",
        )
        return

    if step == "remove_account":
        command = normalize_management_command(text)
        match = re.fullmatch(r"REMOVE\s+(A\d+)", command)
        account = find_account(state, match.group(1) if match else "")
        if not account:
            await send_panel(update, "⟦ sᴇɴᴅ ʀᴇᴍᴏᴠᴇ ᴀɴ ᴀᴄᴄᴏᴜɴᴛ ɪᴅ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ⟧")
            return
        for repo_id, target in list(state.repositories.items()):
            if target.account_id == account.account_id:
                stop_schedule(target)
                state.repositories.pop(repo_id, None)
        state.accounts.pop(account.account_id, None)
        clear_flow(context)
        await send_panel(update, f"⟦ ᴀᴄᴄᴏᴜɴᴛ ᴀɴᴅ ʟɪɴᴋᴇᴅ ʀᴇᴘᴏs ʀᴇᴍᴏᴠᴇᴅ · {account.account_id} ⟧")
        return

    if step == "manage_repo":
        command = normalize_management_command(text)
        match = re.fullmatch(r"(REMOVE|START|STOP)\s+(R\d+)", command)
        if not match:
            await send_panel(update, "⟦ sᴇɴᴅ ʀᴇᴍᴏᴠᴇ ʀ1, sᴛᴀʀᴛ ʀ1, ᴏʀ sᴛᴏᴘ ʀ1 ⟧")
            return
        operation, repo_id = match.group(1).upper(), match.group(2).upper()
        target = find_repository(state, repo_id)
        if not target:
            await send_panel(update, "⟦ ʀᴇᴘᴏ ɪᴅ ɴᴏᴛ ғᴏᴜɴᴅ ⟧")
            return
        if operation == "REMOVE":
            stop_schedule(target)
            state.repositories.pop(target.repo_id, None)
            clear_flow(context)
            await send_panel(update, f"⟦ ʀᴇᴘᴏsɪᴛᴏʀʏ ʀᴇᴍᴏᴠᴇᴅ · {target.repo_id} ⟧")
        elif operation == "START":
            started = start_schedule(user_id, target, context)
            clear_flow(context)
            await send_panel(update, f"⟦ {target.repo_id} · {'sᴄʜᴇᴅᴜʟᴇ sᴛᴀʀᴛᴇᴅ' if started else 'ᴀʟʀᴇᴀᴅʏ ᴀᴄᴛɪᴠᴇ'} ⟧")
        else:
            stopped = stop_schedule(target)
            clear_flow(context)
            await send_panel(update, f"⟦ {target.repo_id} · {'sᴄʜᴇᴅᴜʟᴇ sᴛᴏᴘᴘᴇᴅ' if stopped else 'ɴᴏᴛ ᴀᴄᴛɪᴠᴇ'} ⟧")
        return

    if step == "file_repo":
        target = find_repository(state, text)
        if not target:
            await send_panel(update, "⟦ ʀᴇᴘᴏ ɪᴅ ɴᴏᴛ ғᴏᴜɴᴅ · sᴇɴᴅ ᴀɴ ɪᴅ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ⟧")
            return
        context.user_data["selected_repo_id"] = target.repo_id
        context.user_data["flow_step"] = "file_path_value"
        await send_panel(
            update,
            f"⟦ ʙᴏᴛ ғɪʟᴇ ɴᴀᴍᴇ · {target.repo_id} ⟧\n\n"
            "sᴇɴᴅ ᴀ ʀᴇʟᴀᴛɪᴠᴇ ᴘᴀᴛʜ, ғᴏʀ ᴇxᴀᴍᴘʟᴇ: ᴀʙᴄᴅ.ᴊs ᴏʀ ᴅᴀᴛᴀ/ᴀʙᴄᴅ.json."
        )
        return

    if step == "file_path_value":
        target = find_repository(state, context.user_data.get("selected_repo_id", ""))
        file_path = normalize_file_path(text)
        if not target or not file_path:
            await send_panel(update, "⟦ ғɪʟᴇ ᴘᴀᴛʜ ɪs ɪɴᴠᴀʟɪᴅ · ᴛʀʏ ᴀ ʀᴇʟᴀᴛɪᴠᴇ ғɪʟᴇ ɴᴀᴍᴇ ⟧")
            return
        target.file_path = file_path
        clear_flow(context)
        await send_panel(update, f"⟦ ʙᴏᴛ ғɪʟᴇ sᴇᴛ · {target.repo_id} · {file_path} ⟧")
        return

    if step == "upload_repo":
        target = find_repository(state, text)
        if not target:
            await send_panel(update, "⟦ ʀᴇᴘᴏ ɪᴅ ɴᴏᴛ ғᴏᴜɴᴅ · sᴇɴᴅ ᴀɴ ɪᴅ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ⟧")
            return
        context.user_data["selected_repo_id"] = target.repo_id
        context.user_data["flow_step"] = "upload_document"
        await send_panel(
            update,
            f"⟦ ᴜᴘʟᴏᴀᴅ ғɪʟᴇ · {target.repo_id} ⟧\n\n"
            f"sᴇɴᴅ ᴀ ᴛᴇʟᴇɢʀᴀᴍ ᴅᴏᴄᴜᴍᴇɴᴛ ᴜᴘ ᴛᴏ {MAX_UPLOAD_BYTES // 1000} ᴋʙ.\n"
            "ɪᴛ ᴡɪʟʟ ʙᴇ ᴄᴏᴍᴍɪᴛᴛᴇᴅ ɴᴏᴡ ᴜsɪɴɢ ɪᴛs ғɪʟᴇ ɴᴀᴍᴇ.",
        )
        return

    if step == "upload_document":
        await send_panel(update, "⟦ sᴇɴᴅ ᴛʜᴇ ғɪʟᴇ ᴀs ᴀ ᴛᴇʟᴇɢʀᴀᴍ ᴅᴏᴄᴜᴍᴇɴᴛ, ᴏʀ ᴜsᴇ /cancel ⟧")
        return

    if step == "interval_repo":
        target = find_repository(state, text)
        if not target:
            await send_panel(update, "⟦ ʀᴇᴘᴏ ɪᴅ ɴᴏᴛ ғᴏᴜɴᴅ · sᴇɴᴅ ᴀɴ ɪᴅ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ⟧")
            return
        context.user_data["selected_repo_id"] = target.repo_id
        context.user_data["flow_step"] = "interval_value"
        await send_panel(
            update,
            f"⟦ ɪɴᴛᴇʀᴠᴀʟ · {target.repo_id} ⟧\n\n"
            f"sᴇɴᴅ ᴍɪɴᴜᴛᴇs · {MIN_INTERVAL_MINUTES}–{MAX_INTERVAL_MINUTES}.\n"
            f"ᴄᴜʀʀᴇɴᴛ · {target.interval_minutes}",
        )
        return

    if step == "interval_value":
        target = find_repository(state, context.user_data.get("selected_repo_id", ""))
        try:
            interval = int(text)
        except ValueError:
            await send_panel(update, "⟦ sᴇɴᴅ ᴀ ᴡʜᴏʟᴇ ɴᴜᴍʙᴇʀ ɪɴ ᴍɪɴᴜᴛᴇs ⟧")
            return
        if not target or not MIN_INTERVAL_MINUTES <= interval <= MAX_INTERVAL_MINUTES:
            await send_panel(update, f"⟦ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟᴜᴇ ʙᴇᴛᴡᴇᴇɴ {MIN_INTERVAL_MINUTES} ᴀɴᴅ {MAX_INTERVAL_MINUTES} ⟧")
            return
        target.interval_minutes = interval
        clear_flow(context)
        await send_panel(update, f"⟦ {target.repo_id} · ɪɴᴛᴇʀᴠᴀʟ sᴇᴛ · {interval} ᴍɪɴ ⟧")
        return

    if step == "message_repo":
        target = find_repository(state, text)
        if not target:
            await send_panel(update, "⟦ ʀᴇᴘᴏ ɪᴅ ɴᴏᴛ ғᴏᴜɴᴅ · sᴇɴᴅ ᴀɴ ɪᴅ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ⟧")
            return
        context.user_data["selected_repo_id"] = target.repo_id
        context.user_data["flow_step"] = "message_value"
        await send_panel(
            update,
            f"⟦ ᴄᴏᴍᴍɪᴛ ᴍᴇssᴀɢᴇ · {target.repo_id} ⟧\n\n"
            "sᴇɴᴅ ᴀ ᴄᴜsᴛᴏᴍ ᴍᴇssᴀɢᴇ ᴏʀ ᴛʏᴘᴇ ᴅᴇғᴀᴜʟᴛ ᴛᴏ ᴜsᴇ ᴛɪᴍᴇsᴛᴀᴍᴘs.",
        )
        return

    if step == "message_value":
        target = find_repository(state, context.user_data.get("selected_repo_id", ""))
        if not target:
            clear_flow(context)
            await send_panel(update, "⟦ ʀᴇᴘᴏ ɴᴏᴛ ғᴏᴜɴᴅ ⟧")
            return
        if text.casefold() in {"default", "ᴅᴇғᴀᴜʟᴛ"}:
            target.message_mode = "default"
            target.custom_message = ""
        elif 1 <= len(text) <= 200 and "\n" not in text and "\r" not in text:
            target.message_mode = "custom"
            target.custom_message = text
        else:
            await send_panel(update, "⟦ ᴍᴇssᴀɢᴇ ᴍᴜsᴛ ʙᴇ 1–200 ᴄʜᴀʀᴀᴄᴛᴇʀs ᴏɴ ᴏɴᴇ ʟɪɴᴇ ⟧")
            return
        clear_flow(context)
        await send_panel(update, f"⟦ {target.repo_id} · ᴄᴏᴍᴍɪᴛ ᴍᴇssᴀɢᴇ sᴀᴠᴇᴅ ⟧")
        return

    if step == "commit_repo":
        target = find_repository(state, text)
        if not target:
            await send_panel(update, "⟦ ʀᴇᴘᴏ ɪᴅ ɴᴏᴛ ғᴏᴜɴᴅ · sᴇɴᴅ ᴀɴ ɪᴅ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ⟧")
            return
        account = state.accounts.get(target.account_id)
        if not account:
            clear_flow(context)
            await send_panel(update, "⟦ ʟɪɴᴋᴇᴅ ᴀᴄᴄᴏᴜɴᴛ ɴᴏᴛ ғᴏᴜɴᴅ ⟧")
            return
        clear_flow(context)
        try:
            target.last_commit = await create_activity_commit(account, target)
            target.last_error = ""
            await send_panel(update, f"⟦ ᴄᴏᴍᴍɪᴛ sᴜᴄᴄᴇss · {target.repo_id} · {target.last_commit} ⟧")
        except GitHubError as error:
            target.last_error = f"ɢɪᴛʜᴜʙ ʀᴇǫᴜᴇsᴛ ғᴀɪʟᴇᴅ · {error.status_code}"
            await send_panel(update, f"⟦ {target.repo_id} · {target.last_error} ⟧")
        except (httpx.HTTPError, ValueError, UnicodeError, json.JSONDecodeError):
            target.last_error = "ғɪʟᴇ ᴏʀ ɴᴇᴛᴡᴏʀᴋ ᴇʀʀᴏʀ"
            await send_panel(update, f"⟦ {target.repo_id} · {target.last_error} ⟧")
        return

    await send_panel(update, "⟦ ᴜsᴇ ᴀ ᴋᴇʏʙᴏᴀʀᴅ ᴄᴏɴᴛʀᴏʟ ᴏʀ ᴛʏᴘᴇ /cancel ⟧")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_private(update):
        await update.effective_message.reply_text("ᴘʟᴇᴀsᴇ ᴜsᴇ ᴛʜɪs ʙᴏᴛ ɪɴ ᴀ ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ.")
        return
    user_id = update.effective_user.id
    step = context.user_data.get("flow_step")
    if step != "upload_document":
        await send_panel(update, "⟦ ᴛᴀᴘ ᴜᴘʟᴏᴀᴅ ғɪʟᴇ ᴀɴᴅ sᴇʟᴇᴄᴛ ᴀ ʀᴇᴘᴏ ғɪʀsᴛ ⟧")
        return
    document = update.effective_message.document
    if document.file_size and document.file_size > MAX_UPLOAD_BYTES:
        clear_flow(context)
        await send_panel(update, f"⟦ ғɪʟᴇ ᴛᴏᴏ ʟᴀʀɢᴇ · ᴍᴀx {MAX_UPLOAD_BYTES // 1000} ᴋʙ ⟧")
        return
    state = get_user_state(context, user_id)
    target = find_repository(state, context.user_data.get("selected_repo_id", ""))
    account = state.accounts.get(target.account_id) if target else None
    if not target or not account:
        clear_flow(context)
        await send_panel(update, "⟦ ʀᴇᴘᴏ ᴏʀ ᴀᴄᴄᴏᴜɴᴛ ɴᴏᴛ ғᴏᴜɴᴅ ⟧")
        return
    raw_name = document.file_name or ""
    filename = raw_name.replace("\\", "/").split("/")[-1]
    file_path = normalize_file_path(filename)
    if not file_path:
        clear_flow(context)
        await send_panel(update, "⟦ ғɪʟᴇ ɴᴀᴍᴇ ɪs ɴᴏᴛ sᴜᴘᴘᴏʀᴛᴇᴅ ⟧")
        return
    try:
        telegram_file = await context.bot.get_file(document.file_id)
        content = bytes(await telegram_file.download_as_bytearray())
        if len(content) > MAX_UPLOAD_BYTES:
            clear_flow(context)
            await send_panel(update, f"⟦ ғɪʟᴇ ᴛᴏᴏ ʟᴀʀɢᴇ · ᴍᴀx {MAX_UPLOAD_BYTES // 1000} ᴋʙ ⟧")
            return
        commit_sha = await create_uploaded_commit(account, target, file_path, content)
    except GitHubError as error:
        target.last_error = f"ɢɪᴛʜᴜʙ ʀᴇǫᴜᴇsᴛ ғᴀɪʟᴇᴅ · {error.status_code}"
        await send_panel(update, f"⟦ ᴜᴘʟᴏᴀᴅ ᴄᴏᴍᴍɪᴛ ғᴀɪʟᴇᴅ · {target.last_error} ⟧")
        return
    except (httpx.HTTPError, UnicodeError):
        await send_panel(update, "⟦ ғɪʟᴇ ᴜᴘʟᴏᴀᴅ ғᴀɪʟᴇᴅ · ᴛʀʏ ᴀɢᴀɪɴ ⟧")
        return
    except Exception as error:
        logger.error("File transfer failed: %s", type(error).__name__)
        await send_panel(update, "⟦ ғɪʟᴇ ᴄᴏᴜʟᴅ ɴᴏᴛ ʙᴇ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ ⟧")
        return
    clear_flow(context)
    target.last_commit = commit_sha
    target.last_error = ""
    await send_panel(update, f"⟦ ғɪʟᴇ ᴄᴏᴍᴍɪᴛᴛᴇᴅ · {target.repo_id} · {file_path} · {commit_sha} ⟧")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if isinstance(error, asyncio.CancelledError):
        return
    logger.error("Unhandled bot error: %s", type(error).__name__)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⟦ ᴜɴᴇxᴘᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ · ᴛʀʏ ᴀɢᴀɪɴ ⟧",
                reply_markup=main_keyboard(),
            )
        except Exception:
            pass


def main() -> None:
    bot_token = get_bot_token()
    if not bot_token:
        raise SystemExit(
            "sᴇᴛ ᴛᴇʟᴇɢʀᴀᴍ_ʙᴏᴛ_ᴛᴏᴋᴇɴ ɪɴ ᴛʜᴇ ᴇɴᴠɪʀᴏɴᴍᴇɴᴛ ᴏʀ ᴜsᴇ ʜᴀʀᴅᴄᴏᴅᴇᴅ ᴄᴏɴғɪɢ."
        )
    application = Application.builder().token(bot_token).build()
    application.bot_data["users"] = {}
    application.bot_data["admin_ids"] = load_admin_ids()
    if not application.bot_data["admin_ids"]:
        logger.warning("No admin user IDs configured; admin-only commands are disabled")
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("admin_stats", admin_stats_command))
    application.add_handler(CommandHandler("admin_users", admin_users_command))
    application.add_handler(CommandHandler("admin_stopall", admin_stopall_command))
    application.add_handler(CommandHandler("admin_reset", admin_reset_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(error_handler)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
