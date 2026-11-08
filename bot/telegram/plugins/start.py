import re
from urllib.parse import quote
from os.path import splitext
from asyncio import sleep

from pyrogram import filters, Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from pyrogram.enums.parse_mode import ParseMode

from bot import LOGGER
from bot.config import Telegram
from bot.helper.database import Database
from bot.helper.file_size import get_readable_file_size
from bot.helper.index import get_messages
from bot.helper.media import is_media
from bot.telegram import StreamBot

db = Database()


def get_base_url():
    return Telegram.BASE_URL.rstrip('/') if Telegram.BASE_URL else "http://127.0.0.1:8080"


@StreamBot.on_message(filters.command('start') & filters.private)
async def start_handler(bot: Client, message: Message):
    if len(message.command) > 1 and "file_" in message.text:
        try:
            usr_cmd = message.text.split("_")[-1]
            data = usr_cmd.split("-")
            message_id, chat_id = data[0], f"-{data[1]}"
            file = await bot.get_messages(int(chat_id), int(message_id))
            media = is_media(file)
            await message.reply_cached_media(file_id=media.file_id, caption=f'**{media.file_name}**')
            return
        except Exception as e:
            LOGGER.error(f"Error serving cached media in start: {e}")

    base_url = get_base_url()
    welcome_text = (
        "👋 **Welcome to Surf-TG Stream CDN Bot!**\n\n"
        "⚡ I automatically store your media files in Telegram cloud storage and provide permanent, "
        "high-speed **Stream CDN links**, browser video player links, and direct download links.\n\n"
        "**Features:**\n"
        "• Send or forward any video/document directly to this chat.\n"
        "• Instant HTTP-206 Range Streaming (compatible with VLC, MX Player, IINA, browsers).\n"
        "• Web portal with media playlists, multi-client rotation, and search.\n\n"
        f"🌐 **Web Portal:** {base_url}"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Open Web Portal", url=base_url)],
    ])

    await message.reply_text(welcome_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


@StreamBot.on_message(filters.command('index'))
async def index_handler(bot: Client, message: Message):
    channel_id = message.chat.id
    auth_var = await db.get_variable('auth_channel')
    if auth_var and auth_var.strip():
        auth_channels = [c.strip() for c in auth_var.split(",") if c.strip()]
    else:
        auth_channels = Telegram.AUTH_CHANNEL

    if str(channel_id) in auth_channels or f"-100{str(channel_id).replace('-100', '')}" in auth_channels:
        try:
            last_id = message.id
            start_message = (
                "🔄 Please perform this action only once at the beginning of Surf-TG usage.\n\n"
                "📋 File listing is currently in progress.\n\n"
                "🚫 Please refrain from sending any additional files or indexing other channels until this process completes.\n\n"
                "⏳ Please be patient and wait a few moments."
            )

            wait_msg = await message.reply(text=start_message)
            files = await get_messages(message.chat.id, 1, last_id)
            await db.add_btgfiles(files)
            await wait_msg.delete()
            done_message = (
                "✅ All your files have been successfully stored in the database. You're all set!\n\n"
                "📁 You don't need to index again unless you make changes to the database."
            )

            await bot.send_message(chat_id=message.chat.id, text=done_message)
        except FloodWait as e:
            LOGGER.info(f"Sleeping for {str(e.value)}s")
            await sleep(e.value)
            await message.reply(text=f"Got Floodwait of {str(e.value)}s",
                                disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(text="Channel is not in AUTH_CHANNEL")


@StreamBot.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
    )
)
async def private_file_receive_handler(bot: Client, message: Message):
    """
    Handles media uploaded directly in Private Chat.
    Copies the file into Telegram cloud storage channel, registers in DB,
    and replies with Stream CDN, Watch, and Download links.
    """
    try:
        media = message.video or message.document or message.audio
        if not media:
            return

        # Determine target cloud storage channel
        auth_var = await db.get_variable('auth_channel')
        channel_candidates = []
        if auth_var and auth_var.strip():
            channel_candidates.extend([c.strip() for c in auth_var.split(',') if c.strip()])
        if Telegram.AUTH_CHANNEL:
            channel_candidates.extend(Telegram.AUTH_CHANNEL)
        if getattr(Telegram, 'BIN_CHANNEL', None):
            channel_candidates.append(str(Telegram.BIN_CHANNEL))

        target_channel = None
        for cand in channel_candidates:
            if cand:
                cleaned = str(cand).strip()
                target_channel = int(cleaned) if cleaned.lstrip('-').isdigit() else cleaned
                break

        # Save to storage channel if configured
        if target_channel:
            try:
                sent_msg = await message.copy(chat_id=target_channel)
                storage_chat_id = sent_msg.chat.id
                storage_msg_id = sent_msg.id
                media = sent_msg.video or sent_msg.document or sent_msg.audio
            except Exception as e:
                LOGGER.error(f"Failed to copy media to storage channel {target_channel}: {e}")
                storage_chat_id = message.chat.id
                storage_msg_id = message.id
        else:
            storage_chat_id = message.chat.id
            storage_msg_id = message.id

        raw_title = media.file_name or message.caption or f"Media_{storage_msg_id}"
        title = re.sub(r'[.,|_\',]', ' ', splitext(raw_title)[0])
        full_filename = media.file_name or f"{title}.mp4"
        secure_hash = media.file_unique_id[:6]
        size_str = get_readable_file_size(media.file_size)
        mime_type = media.mime_type or "video/mp4"

        # Persist in DB files table
        await db.add_tgfiles(
            chat_id=str(storage_chat_id),
            file_id=str(storage_msg_id),
            hash=str(secure_hash),
            name=str(title),
            size=str(size_str),
            file_type=str(mime_type)
        )

        # Persist to Playlist table (root directory)
        await db.add_json([{
            'parent_folder': 'root',
            'name': full_filename,
            'thumbnail': '',
            'type': 'file',
            'chat_id': str(storage_chat_id),
            'file_id': int(storage_msg_id),
            'hash': str(secure_hash),
            'size': str(size_str),
            'file_type': str(mime_type)
        }])

        clean_cid = str(storage_chat_id).replace("-100", "")
        enc_name = quote(full_filename)
        base_url = get_base_url()

        stream_url = f"{base_url}/{clean_cid}/{enc_name}?id={storage_msg_id}&hash={secure_hash}"
        watch_url = f"{base_url}/watch/{clean_cid}?id={storage_msg_id}&hash={secure_hash}"
        download_url = f"{base_url}/{clean_cid}/{enc_name}?id={storage_msg_id}&hash={secure_hash}"

        reply_text = (
            "⚡ **Your Stream CDN Link is Ready!**\n\n"
            f"📁 **File:** `{full_filename}`\n"
            f"💾 **Size:** `{size_str}`\n"
            f"☁️ **Storage Channel ID:** `{storage_chat_id}`\n\n"
            f"🔗 **Stream CDN URL:**\n`{stream_url}`\n\n"
            f"▶️ **Online Player URL:**\n`{watch_url}`\n\n"
            f"📥 **Direct Download URL:**\n`{download_url}`"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Watch Online", url=watch_url), InlineKeyboardButton("⚡ Stream CDN", url=stream_url)],
            [InlineKeyboardButton("📥 Direct Download", url=download_url), InlineKeyboardButton("🌐 Web Portal", url=base_url)]
        ])

        await message.reply_text(
            reply_text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
            parse_mode=ParseMode.MARKDOWN
        )

    except FloodWait as e:
        LOGGER.info(f"Floodwait: sleeping {e.value}s")
        await sleep(e.value)
    except Exception as e:
        LOGGER.error(f"Error handling private media: {e}", exc_info=True)
        await message.reply_text(f"❌ Error generating Stream CDN link: {str(e)}")


@StreamBot.on_message(
    filters.channel
    & (
        filters.document
        | filters.video
        | filters.audio
    )
)
async def channel_file_receive_handler(bot: Client, message: Message):
    channel_id = message.chat.id
    auth_var = await db.get_variable('auth_channel')
    if auth_var and auth_var.strip():
        auth_channels = [c.strip() for c in auth_var.split(",") if c.strip()]
    else:
        auth_channels = Telegram.AUTH_CHANNEL

    clean_cid = str(channel_id).replace("-100", "")
    is_authorized = (
        str(channel_id) in auth_channels 
        or f"-100{clean_cid}" in auth_channels 
        or clean_cid in auth_channels
    )

    if is_authorized:
        try:
            file = message.video or message.document or message.audio
            raw_title = file.file_name or message.caption or file.file_id
            title = re.sub(r'[.,|_\',]', ' ', splitext(raw_title)[0])
            full_filename = file.file_name or f"{title}.mp4"
            msg_id = message.id
            hash_val = file.file_unique_id[:6]
            size = get_readable_file_size(file.file_size)
            mime_type = file.mime_type or "video/mp4"

            await db.add_tgfiles(str(channel_id), str(msg_id), str(hash_val), str(title), str(size), str(mime_type))

            # Also persist to playlist table
            await db.add_json([{
                'parent_folder': 'root',
                'name': full_filename,
                'thumbnail': '',
                'type': 'file',
                'chat_id': str(channel_id),
                'file_id': int(msg_id),
                'hash': str(hash_val),
                'size': str(size),
                'file_type': str(mime_type)
            }])

            base_url = get_base_url()
            enc_name = quote(full_filename)
            stream_url = f"{base_url}/{clean_cid}/{enc_name}?id={msg_id}&hash={hash_val}"
            LOGGER.info(f"Indexed channel media: {full_filename} -> {stream_url}")

        except FloodWait as e:
            LOGGER.info(f"Sleeping for {str(e.value)}s")
            await sleep(e.value)
        except Exception as e:
            LOGGER.error(f"Error handling channel file: {e}")
    else:
        LOGGER.warning(f"Ignored channel {channel_id}: not in AUTH_CHANNEL")


@StreamBot.on_message(filters.command('stream'))
async def stream_command_handler(bot: Client, message: Message):
    """
    Generate Stream CDN link for replied media in groups or PM.
    """
    replied = message.reply_to_message
    if not replied or not (replied.video or replied.document or replied.audio):
        await message.reply_text("ℹ️ Please reply to a video, audio, or document with `/stream` to generate a CDN link.")
        return

    # Delegate to private_file_receive_handler logic using the replied message
    await private_file_receive_handler(bot, replied)
