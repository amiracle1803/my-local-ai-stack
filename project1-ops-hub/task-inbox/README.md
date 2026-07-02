# Drop tasks here

Put a plain `.txt` or `.md` file in this folder with a task written in normal
English, then run `run-inbox.bat` (or let the scheduled task pick it up).

Examples of a file's contents:

- "Plan a 3-week beginner running plan, 3 days a week."
- "Draft a friendly reply asking to reschedule to next Thursday: <paste email>"
- "Summarise these: https://example.com/a  https://example.com/b"

Results appear in `../task-outbox/`. The original file is moved to `../done/`
so it isn't run twice.
