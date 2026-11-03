You are writing the voice-over script for a short (or YouTube) story video that reads a
social media post aloud. Write ONLY in {{language}}.

Rules:
- Keep the facts, the storyline and the author's point of view. Do not invent events.
- Transform, don't copy: tighten, clarify and make it sound spoken. Translate if the post is in another language.
- Length: about {{target_sec}} seconds of speech, at most {{max_words}} words in total (hook + segments + cta).
- `hook`: one punchy sentence (max 18 words) read while the post title card is on screen.
- `segments`: the story in order, each 1-3 short sentences (one caption screen each). No emojis, no
  markdown, no stage directions. Write numbers the way they are spoken.
- If top comments are given and useful, you may add 1-3 short segments about them at the end
  ("One commenter said ...").
- `cta`: one short closing question inviting comments. Base it on: "{{cta_hint}}".
- `title`: short card title (max 90 characters) in {{language}}.
- `description`: 1-2 sentences for the upload description, crediting the {{platform}} source.
- `hashtags`: 3-6 relevant hashtags without spaces.
- Remove personal data (full names, addresses, phone numbers) of private people.

Source platform: {{platform}} / {{community}}
Post title: {{title}}

Post body:
"""
{{body}}
"""

Top comments:
{{comments}}

Return JSON only, matching the schema.
