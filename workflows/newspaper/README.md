# N1 · newspaper

News article → short news video: headline card over the lead photo, photo beats with Ken Burns, quote lower-third,
big-number card, word captions (`news_pop`), source chip on every photo.

```powershell
# a site without a bot check
studio new newspaper "de-mau-dgnl" --url "https://..."
# a site with a bot check (e.g. laodong.vn): Ctrl+S in the browser -> "Web page, HTML only"
studio new newspaper "de-mau-dgnl" --text-file ".\Thoi gian cong bo de mau.html"
studio run "projects\newspaper\<ngay>_de-mau-dgnl"
```

See `docs/WORKFLOWS.md` (N1) for the stages and options.
