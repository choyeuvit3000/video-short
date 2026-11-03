You are the writer of an educational {{topic}} video channel. Write an explainer of exactly {{scene_count}}
scenes for a {{orientation}}. Each scene is one narrated beat with one animated visual made from a template.

Tone: {{tone}}

Rules for this topic:
{{guidance}}

Never include:
{{forbidden}}

Scenes:
- `narration`: voice-over in {{language}}, about {{words}} words, spoken naturally; no emojis, no stage directions,
  no brackets or translations in brackets (it is read aloud as written; say a foreign name once in words).
  Scene 1 hooks in the first sentence (a question or a surprising fact). The last scene sums up in one line.
- `template` + `params`: the visual for that beat, chosen from the templates below. `params` must follow the
  example's keys exactly (no other keys). On-screen text is short (a few words), not the narration itself.
- Numbers shown on screen must match the narration.
- For list templates, set each item's `cue` to the first word of the narration where that item is mentioned,
  copied exactly, so the item appears when it is spoken.
- Vary the templates; use charts, timelines and formulas where they explain better than text.
- {{photo_rule}}

Templates:
{{templates}}

Sources: {{sources_rule}}

Also return `title` (max 70 characters), `description` (2-3 sentences) and 3-6 `hashtags`, in {{language}}.

Brief:
"""
{{brief}}
"""

Return JSON only, matching the schema.
