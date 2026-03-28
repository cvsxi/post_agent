from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import html
import json


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    body: str
    topic: str
    status: str
    image: str | None = None
    queue_order: int | None = None

    def render_html(self) -> str:
        escaped_title = html.escape(self.title)
        escaped_body = html.escape(self.body)
        return f"<b>{escaped_title}</b>\n\n{escaped_body}"

    def render_review_html(self) -> str:
        escaped_topic = html.escape(self.topic)
        return f"<i>{escaped_topic}</i>\n\n{self.render_html()}"


class PostLibrary:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._posts = self._load_posts()

    def _load_posts(self) -> list[Post]:
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        posts = payload.get("posts", [])
        return [Post(**item) for item in posts]

    @property
    def total_count(self) -> int:
        return len(self._posts)

    @property
    def posts(self) -> list[Post]:
        return list(self._posts)

    def _save_posts(self) -> None:
        payload = {
            "posts": [
                {
                    "slug": post.slug,
                    "title": post.title,
                    "body": post.body,
                    "topic": post.topic,
                    "status": post.status,
                    "image": post.image,
                    "queue_order": post.queue_order,
                }
                for post in self._posts
            ]
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def next_unsent(self, sent_slugs: set[str]) -> Post | None:
        queued = self.queued_posts(sent_slugs, limit=1)
        return queued[0] if queued else None

    def sent_count(self, sent_slugs: set[str]) -> int:
        return sum(1 for post in self._posts if post.slug in sent_slugs)

    def approved_count(self, sent_slugs: set[str]) -> int:
        return sum(
            1
            for post in self._posts
            if post.status == "approved" and post.slug not in sent_slugs
        )

    def queued_posts(self, sent_slugs: set[str], limit: int | None = None) -> list[Post]:
        approved_with_index = [
            (index, post)
            for index, post in enumerate(self._posts)
            if post.status == "approved" and post.slug not in sent_slugs
        ]
        approved_with_index.sort(
            key=lambda item: (
                item[1].queue_order is None,
                item[1].queue_order if item[1].queue_order is not None else item[0],
                item[0],
            )
        )
        posts = [post for _, post in approved_with_index]
        if limit is None:
            return posts
        return posts[:limit]

    def pending_count(self) -> int:
        return sum(1 for post in self._posts if post.status == "pending_review")

    def get_by_slug(self, slug: str) -> Post | None:
        target = slug.strip().lower()
        for post in self._posts:
            if post.slug == target:
                return post
        return None

    def topics_with_pending_posts(self) -> list[str]:
        seen: list[str] = []
        for post in self._posts:
            if post.status != "pending_review":
                continue
            if post.topic not in seen:
                seen.append(post.topic)
        return seen

    def first_pending(self, topic: str | None = None) -> Post | None:
        for post in self._posts:
            if post.status != "pending_review":
                continue
            if topic is not None and post.topic != topic:
                continue
            return post
        return None

    def approve(self, slug: str) -> Post | None:
        updated_posts: list[Post] = []
        approved_post: Post | None = None
        next_queue_order = (
            max((post.queue_order or 0) for post in self._posts if post.status == "approved")
            + 1
        )

        for post in self._posts:
            if post.slug == slug and post.status == "pending_review":
                approved_post = Post(
                    slug=post.slug,
                    title=post.title,
                    body=post.body,
                    topic=post.topic,
                    status="approved",
                    image=post.image,
                    queue_order=next_queue_order,
                )
                updated_posts.append(approved_post)
            else:
                updated_posts.append(post)

        if approved_post is None:
            return None

        self._posts = updated_posts
        self._save_posts()
        return approved_post

    def reject_and_delete(self, slug: str) -> Post | None:
        rejected_post: Post | None = None
        updated_posts: list[Post] = []

        for post in self._posts:
            if post.slug == slug and post.status == "pending_review":
                rejected_post = post
                continue
            updated_posts.append(post)

        if rejected_post is None:
            return None

        self._posts = updated_posts
        self._save_posts()
        return rejected_post
