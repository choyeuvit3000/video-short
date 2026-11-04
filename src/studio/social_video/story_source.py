"""Shared story layout can carry different sources without changing their attribution."""


def labels(story):
    author = story.get("author", "").lstrip("@")
    if story.get("platform") == "threads":
        return "Threads", "@" + author
    return "r/" + story.get("sub", "nosleep"), "u/" + author


def credit(story):
    platform, author = labels(story)
    return f"Nguồn: {platform} · {author} · {story.get('url', '')}"


def mode(story):
    return "threads_story" if story.get("platform") == "threads" else "reddit"
