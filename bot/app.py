from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings, load_settings
from .content import Post, PostLibrary
from .state import RuntimeState, StateStore

LOGGER = logging.getLogger(__name__)

HELP_TEXT = "\n".join(
    [
        "Команди керування:",
        "статус - поточний стан бота і каналу",
        "наступний - показати наступний пост",
        "пости - показати наступні 5 постів",
        "пост <slug> - показати конкретний пост",
        "опублікуй - відправити наступний пост зараз, якщо сьогоднішній слот ще вільний",
        "модерація - показати наступний пост на погодження",
        "теми - вибрати тему для перегляду чернеток",
        "канал - показати поточну прив'язку каналу",
        "допомога - показати це меню",
    ]
)

OWNER_MENU = ReplyKeyboardMarkup(
    keyboard=[
        ["Статус", "Канал"],
        ["Наступний", "Пости"],
        ["Опублікуй", "Пост за slug"],
        ["Модерація", "Теми"],
        ["Допомога"],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Оберіть дію або напишіть команду",
)


@dataclass
class Services:
    settings: Settings
    posts: PostLibrary
    state_store: StateStore


def _get_services(application: Application) -> Services:
    return application.bot_data["services"]


def _get_target_chat_id(state: RuntimeState, settings: Settings) -> int | str | None:
    return state.bound_channel_id or settings.default_channel_id


def _now_in_tz(settings: Settings) -> datetime:
    return datetime.now(settings.timezone)


def _display_name(update: Update) -> str:
    user = update.effective_user
    if user is None:
        return "unknown"

    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return full_name or user.username or str(user.id)


def _append_inbox_entry(
    services: Services,
    update: Update,
    entry_type: str = "message",
) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        return

    entry = {
        "timestamp": _now_in_tz(services.settings).isoformat(),
        "entry_type": entry_type,
        "chat_id": chat.id,
        "chat_type": chat.type,
        "message_id": message.message_id,
        "user_id": user.id,
        "username": user.username,
        "display_name": _display_name(update),
        "text": message.text or message.caption or "",
    }
    services.settings.inbox_path.parent.mkdir(parents=True, exist_ok=True)
    with services.settings.inbox_path.open("a", encoding="utf-8") as inbox_file:
        inbox_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def _ensure_owner_access(update: Update, services: Services) -> bool:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None or chat.type != ChatType.PRIVATE:
        return False

    state = services.state_store.load()

    if state.owner_user_id is None:
        configured_owner_id = services.settings.owner_user_id
        if configured_owner_id is not None and user.id != configured_owner_id:
            await message.reply_text("Цей бот вже зарезервований для іншого власника.")
            return False

        state.owner_user_id = user.id
        state.owner_chat_id = chat.id
        state.owner_username = user.username
        state.owner_display_name = _display_name(update)
        services.state_store.save(state)
        LOGGER.info("Registered bot owner: %s (%s)", state.owner_display_name, state.owner_user_id)
        return True

    if state.owner_user_id != user.id:
        await message.reply_text("Доступ заборонено. Цей бот прив'язаний до іншого власника.")
        return False

    if state.owner_chat_id != chat.id or state.owner_username != user.username:
        state.owner_chat_id = chat.id
        state.owner_username = user.username
        state.owner_display_name = _display_name(update)
        services.state_store.save(state)

    return True


def _format_status(services: Services, state: RuntimeState) -> str:
    sent_count = services.posts.sent_count(set(state.sent_slugs))
    approved_count = services.posts.approved_count(set(state.sent_slugs))
    pending_count = services.posts.pending_count()
    next_post = services.posts.next_unsent(set(state.sent_slugs))
    next_title = next_post.title if next_post else "немає запланованих постів"
    channel_title = state.bound_channel_title or "канал ще не прив'язаний"
    channel_id = _get_target_chat_id(state, services.settings) or "не задано"
    last_posted = state.last_published_local_date or "ще нічого не опубліковано"

    return "\n".join(
        [
            f"Канал: {channel_title}",
            f"Channel id: {channel_id}",
            f"Опубліковано: {sent_count}/{services.posts.total_count}",
            f"Відкладено: {approved_count}",
            f"На модерації: {pending_count}",
            f"Остання дата слоту: {last_posted}",
            f"Наступний пост: {next_title}",
            f"Щоденний час: {services.settings.publish_time.strftime('%H:%M')} {services.settings.timezone_name}",
        ]
    )


def _format_post_preview(post: Post) -> str:
    body = post.body.replace("\n\n", " ")
    if len(body) > 280:
        body = body[:277].rstrip() + "..."
    return "\n".join(
        [
            f"{post.title}",
            f"slug: {post.slug}",
            body,
        ]
    )


def _moderation_markup(slug: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Кидати", callback_data=f"approve:{slug}"),
                InlineKeyboardButton("Не кидати", callback_data=f"reject:{slug}"),
            ]
        ]
    )


def _topics_markup(topics: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(topic, callback_data=f"topic:{topic}")]
        for topic in topics
    ]
    return InlineKeyboardMarkup(rows)


async def _notify_owner(application: Application, text: str) -> None:
    services = _get_services(application)
    state = services.state_store.load()
    if state.owner_chat_id is None:
        return

    try:
        await application.bot.send_message(
            chat_id=state.owner_chat_id,
            text=text,
            reply_markup=OWNER_MENU,
        )
    except Exception as error:
        LOGGER.warning("Failed to notify owner chat %s: %s", state.owner_chat_id, error)


async def _send_post(application: Application, services: Services, post: Post) -> bool:
    state = services.state_store.load()
    target_chat_id = _get_target_chat_id(state, services.settings)

    if target_chat_id is None:
        LOGGER.warning("Channel is not bound yet. Skipping scheduled post '%s'.", post.slug)
        return False

    text = post.render_html()
    image_path = services.settings.images_dir / post.image if post.image else None

    if image_path and image_path.exists():
        with image_path.open("rb") as image_stream:
            if len(text) <= 1024:
                await application.bot.send_photo(
                    chat_id=target_chat_id,
                    photo=image_stream,
                    caption=text,
                    parse_mode="HTML",
                )
            else:
                await application.bot.send_photo(chat_id=target_chat_id, photo=image_stream)
                await application.bot.send_message(
                    chat_id=target_chat_id,
                    text=text,
                    parse_mode="HTML",
                )
    else:
        await application.bot.send_message(
            chat_id=target_chat_id,
            text=text,
            parse_mode="HTML",
        )

    if post.slug not in state.sent_slugs:
        state.sent_slugs.append(post.slug)
    state.last_published_local_date = _now_in_tz(services.settings).date().isoformat()
    services.state_store.save(state)

    LOGGER.info("Published post '%s' to %s.", post.slug, target_chat_id)
    return True


async def _publish_next_post(application: Application, reason: str) -> bool:
    services = _get_services(application)
    state = services.state_store.load()
    local_today = _now_in_tz(services.settings).date().isoformat()

    if state.last_published_local_date == local_today:
        LOGGER.info("Skipping publish for %s because today's slot is already used.", reason)
        return False

    next_post = services.posts.next_unsent(set(state.sent_slugs))
    if next_post is None:
        LOGGER.info("No pending posts left to publish.")
        return False

    return await _send_post(application, services, next_post)


async def _daily_publish_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _publish_next_post(context.application, "daily-job")


async def _maybe_publish_catch_up(application: Application) -> None:
    services = _get_services(application)
    local_now = _now_in_tz(services.settings)
    publish_time = services.settings.publish_time

    if local_now.time() < publish_time:
        return

    state = services.state_store.load()
    if state.last_published_local_date == local_now.date().isoformat():
        return

    await _publish_next_post(application, "startup-catchup")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    state = services.state_store.load()
    await update.effective_message.reply_text(
        "\n\n".join(
            [
                "Бот активний. Тепер ти можеш керувати ним з цього чату.",
                _format_status(services, state),
                HELP_TEXT,
            ]
        ),
        reply_markup=OWNER_MENU,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    state = services.state_store.load()
    await update.effective_message.reply_text(
        _format_status(services, state),
        reply_markup=OWNER_MENU,
    )


async def publish_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    published = await _publish_next_post(context.application, "owner-command")
    if published:
        state = services.state_store.load()
        await update.effective_message.reply_text(
            f"Опубліковано. Використано слот {state.last_published_local_date}.",
            reply_markup=OWNER_MENU,
        )
        return

    await update.effective_message.reply_text(
        "Не вдалося опублікувати пост. Або канал ще не прив'язаний, або сьогоднішній слот уже використано, або пости закінчилися.",
        reply_markup=OWNER_MENU,
    )


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    state = services.state_store.load()
    channel_title = state.bound_channel_title or "канал ще не прив'язаний"
    channel_id = _get_target_chat_id(state, services.settings) or "не задано"
    await update.effective_message.reply_text(
        f"Канал: {channel_title}\nChannel id: {channel_id}",
        reply_markup=OWNER_MENU,
    )


async def next_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    state = services.state_store.load()
    next_post = services.posts.next_unsent(set(state.sent_slugs))
    if next_post is None:
        await update.effective_message.reply_text(
            "Черга постів уже вичерпана.",
            reply_markup=OWNER_MENU,
        )
        return

    await update.effective_message.reply_text(
        _format_post_preview(next_post),
        reply_markup=OWNER_MENU,
    )


async def list_posts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    state = services.state_store.load()
    pending = services.posts.queued_posts(set(state.sent_slugs), limit=5)

    if not pending:
        await update.effective_message.reply_text(
            "Запланованих постів більше немає.",
            reply_markup=OWNER_MENU,
        )
        return

    await update.effective_message.reply_text(
        "\n".join(
            [f"{index}. {post.title} [{post.slug}]" for index, post in enumerate(pending, start=1)]
        ),
        reply_markup=OWNER_MENU,
    )


async def show_post_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, slug: str | None = None
) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    target_slug = slug or (" ".join(context.args) if context.args else "")
    target_slug = target_slug.strip().lower()
    if not target_slug:
        await update.effective_message.reply_text(
            "Вкажи slug: пост <slug>",
            reply_markup=OWNER_MENU,
        )
        return

    post = services.posts.get_by_slug(target_slug)
    if post is None:
        await update.effective_message.reply_text(
            "Пост із таким slug не знайдено.",
            reply_markup=OWNER_MENU,
        )
        return

    await update.effective_message.reply_text(
        f"{post.title}\nslug: {post.slug}\n\n{post.body}",
        reply_markup=OWNER_MENU,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    await update.effective_message.reply_text(
        HELP_TEXT,
        reply_markup=OWNER_MENU,
    )


async def moderation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    post = services.posts.first_pending()
    if post is None:
        await update.effective_message.reply_text(
            "У черзі модерації зараз немає постів.",
            reply_markup=OWNER_MENU,
        )
        return

    await update.effective_message.reply_text(
        f"Тема: {post.topic}",
        reply_markup=OWNER_MENU,
    )
    await update.effective_message.reply_text(
        post.render_review_html(),
        parse_mode="HTML",
        reply_markup=_moderation_markup(post.slug),
    )


async def topics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    _append_inbox_entry(services, update)
    topics = services.posts.topics_with_pending_posts()
    if not topics:
        await update.effective_message.reply_text(
            "Тем для модерації зараз немає.",
            reply_markup=OWNER_MENU,
        )
        return

    await update.effective_message.reply_text(
        "Оберіть тему:",
        reply_markup=OWNER_MENU,
    )
    await update.effective_message.reply_text(
        "Теми чернеток:",
        reply_markup=_topics_markup(topics),
    )


async def _show_pending_post_from_topic(
    query_message,
    services: Services,
    topic: str | None,
) -> None:
    post = services.posts.first_pending(topic=topic)
    if post is None:
        text = (
            f"У темі '{topic}' більше немає чернеток."
            if topic is not None
            else "У черзі модерації більше немає чернеток."
        )
        await query_message.reply_text(text, reply_markup=OWNER_MENU)
        return

    await query_message.reply_text(
        f"Тема: {post.topic}",
        reply_markup=OWNER_MENU,
    )
    await query_message.reply_text(
        post.render_review_html(),
        parse_mode="HTML",
        reply_markup=_moderation_markup(post.slug),
    )


async def moderation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        await query.answer()
        return

    data = query.data or ""
    await query.answer()

    if data.startswith("approve:"):
        slug = data.split(":", 1)[1]
        approved = services.posts.approve(slug)
        if approved is None:
            await query.message.reply_text(
                "Цей пост вже не доступний для погодження.",
                reply_markup=OWNER_MENU,
            )
            return

        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"Пост '{approved.title}' додано у відкладену чергу.",
            reply_markup=OWNER_MENU,
        )
        return

    if data.startswith("reject:"):
        slug = data.split(":", 1)[1]
        rejected = services.posts.reject_and_delete(slug)
        if rejected is None:
            await query.message.reply_text(
                "Цей пост вже не доступний для видалення.",
                reply_markup=OWNER_MENU,
            )
            return

        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"Пост '{rejected.title}' видалено з бази.",
            reply_markup=OWNER_MENU,
        )
        return

    if data.startswith("topic:"):
        topic = data.split(":", 1)[1]
        await _show_pending_post_from_topic(query.message, services, topic)
        return


async def private_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _get_services(context.application)
    if not await _ensure_owner_access(update, services):
        return

    message = update.effective_message
    if message is None:
        return

    raw_text = (message.text or "").strip()
    normalized = raw_text.casefold()

    if normalized in {"статус", "status"}:
        await status_command(update, context)
        return
    if normalized in {"допомога", "help", "меню", "menu"}:
        await help_command(update, context)
        return
    if normalized in {"канал", "channel"}:
        await channel_command(update, context)
        return
    if normalized in {"наступний", "next", "next post"}:
        await next_post_command(update, context)
        return
    if normalized in {"пости", "posts", "list"}:
        await list_posts_command(update, context)
        return
    if normalized in {"модерація", "moderation"}:
        await moderation_command(update, context)
        return
    if normalized in {"теми", "topics"}:
        await topics_command(update, context)
        return
    if normalized in {"опублікуй", "publish", "publish now", "post now"}:
        await publish_command(update, context)
        return
    if normalized in {"пост за slug", "post by slug"}:
        await message.reply_text(
            "Надішли команду у форматі: пост <slug>\nНаприклад: пост focus-is-expensive",
            reply_markup=OWNER_MENU,
        )
        return
    if normalized.startswith("пост "):
        await show_post_command(update, context, slug=raw_text[5:])
        return
    if normalized.startswith("post "):
        await show_post_command(update, context, slug=raw_text[5:])
        return

    _append_inbox_entry(services, update)
    await message.reply_text(
        "Повідомлення збережено у локальний inbox, але автоматична дія для нього не визначена.\n\n"
        + HELP_TEXT,
        reply_markup=OWNER_MENU,
    )


async def bind_channel_from_membership(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.my_chat_member is None:
        return

    chat = update.effective_chat
    if chat is None or chat.type != ChatType.CHANNEL:
        return

    new_status = update.my_chat_member.new_chat_member.status
    if new_status not in {"administrator", "member"}:
        return

    services = _get_services(context.application)
    state = services.state_store.load()
    state.bound_channel_id = chat.id
    state.bound_channel_title = chat.title
    services.state_store.save(state)
    LOGGER.info("Bound channel from membership update: %s (%s)", chat.title, chat.id)
    await _notify_owner(
        context.application,
        f"Канал прив'язано: {chat.title} ({chat.id})",
    )
    await _maybe_publish_catch_up(context.application)


async def bind_channel_from_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or chat.type != ChatType.CHANNEL:
        return

    services = _get_services(context.application)
    state = services.state_store.load()
    state.bound_channel_id = chat.id
    state.bound_channel_title = chat.title
    services.state_store.save(state)
    LOGGER.info("Bound channel from channel post: %s (%s)", chat.title, chat.id)
    await _notify_owner(
        context.application,
        f"Канал прив'язано: {chat.title} ({chat.id})",
    )
    await _maybe_publish_catch_up(context.application)


async def post_init(application: Application) -> None:
    services = _get_services(application)
    publish_time = services.settings.publish_time.replace(tzinfo=services.settings.timezone)

    if application.job_queue is None:
        raise RuntimeError(
            "JobQueue is unavailable. Install python-telegram-bot with the job-queue extra."
        )

    application.job_queue.run_daily(
        _daily_publish_job,
        time=publish_time,
        name="daily-post-publish",
    )
    await _maybe_publish_catch_up(application)
    LOGGER.info(
        "Daily job scheduled for %s %s.",
        services.settings.publish_time.strftime("%H:%M"),
        services.settings.timezone_name,
    )


def build_application() -> Application:
    settings = load_settings()
    posts = PostLibrary(settings.posts_path)
    state_store = StateStore(settings.state_path)

    application = (
        ApplicationBuilder().token(settings.token).post_init(post_init).build()
    )
    application.bot_data["services"] = Services(
        settings=settings,
        posts=posts,
        state_store=state_store,
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("publish", publish_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("next", next_post_command))
    application.add_handler(CommandHandler("posts", list_posts_command))
    application.add_handler(CommandHandler("moderation", moderation_command))
    application.add_handler(CommandHandler("topics", topics_command))
    application.add_handler(CommandHandler("post", show_post_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(moderation_callback))
    application.add_handler(
        ChatMemberHandler(bind_channel_from_membership, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    application.add_handler(
        MessageHandler(filters.ChatType.CHANNEL, bind_channel_from_post)
    )
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_text_router)
    )

    return application


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    application = build_application()
    application.run_polling(
        allowed_updates=["message", "channel_post", "my_chat_member", "callback_query"]
    )
