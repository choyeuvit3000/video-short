# N1 · newspaper

News article → short news video: plan one spoken idea per beat, then pick its layout and sourced image.
Shared rules: `assets/shared/layouts/news.yaml`. Layouts: headline, portrait_quote, editorial_photo, document
(text guide card when the source has no verified cover), stat_card, timeline, closing. Two-line phrase captions
(`news_card`), local dark box, word highlight only with real word timings. Content determines the length: no
default duration, word or scene-count cap. Default voice pace is 1.25x (+25%); VieNeu keeps pitch with FFmpeg
atempo, then Whisper aligns captions to the processed audio. Cards still get enough reading time.
More images: all article figures, your images/, plus credited Wikimedia Commons
illustrations per beat's image_query. No API key or paid API required.

`output/scene_plan.json` records actual start/end, narration, layout, asset/source or fallback, text and crop focus.

```powershell
# a site without a bot check
studio new newspaper "de-mau-dgnl" --url "https://..."
# a site with a bot check (e.g. laodong.vn): Ctrl+S in the browser -> "Web page, HTML only"
studio new newspaper "de-mau-dgnl" --text-file ".\Thoi gian cong bo de mau.html"
studio run "projects\newspaper\<ngay>_de-mau-dgnl"
```

See `docs/WORKFLOWS.md` (N1) for the stages and options.
