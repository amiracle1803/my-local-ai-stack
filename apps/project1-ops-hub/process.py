"""
process.py  --  The brain of the Task Dropbox (Project 1).

You give it a task in plain English; it:
  1. Classifies the task into a category.
  2. Routes it to a handler.
  3. Returns finished output (markdown).

Both entry points use this same function:
  - app.py         (a web form you type into)
  - run_inbox.py   (a folder you drop .txt/.md files into)

Design choice / honesty:
  Categories that are fully self-contained -- planning, writing, coding advice,
  general -- produce real, finished output with NO internet and NO extra
  services. They work the moment Ollama is running.

  Categories that normally need the outside world degrade gracefully:
    * research -> if you paste URLs, it fetches + summarises them; otherwise it
                  writes you a research plan (what to look up, what to ask).
    * email    -> it drafts a reply and suggests labels, but does NOT send.
                  Actually sending/labelling lives in Project 3 (n8n + IMAP).
  This keeps Project 1 useful on day one without pretending it can do things
  it can't.
"""

from __future__ import annotations
import sys
from pathlib import Path

# make the repo root importable so `from shared.lib ...` works from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.lib import llm, notes  # noqa: E402
from shared.lib.passes import looped_generate, DEFAULT_SYSTEM  # noqa: E402
from shared.lib.webfetch import fetch_clean  # noqa: E402
from shared.lib.config import load_config  # noqa: E402

CFG = load_config()

CATEGORIES = ["planning", "writing", "research", "coding", "email", "general"]


# --------------------------------------------------------------------------
# Step 1: classification
# --------------------------------------------------------------------------
def classify(task: str) -> str:
    """Return one of CATEGORIES. Defaults to 'general' if unsure."""
    reply = llm.ask(
        "Classify the user's task into exactly ONE of these categories:\n"
        "planning, writing, research, coding, email, general.\n"
        "Reply with only the single category word, lowercase, nothing else.\n\n"
        f"TASK:\n{task}",
        system="You are a precise task router. Output one word only.",
        temperature=0.0,
    )
    word = reply.strip().lower().split()[0].strip(".,:;\"'`") if reply.strip() else ""
    return word if word in CATEGORIES else "general"


# --------------------------------------------------------------------------
# Step 2: handlers
# --------------------------------------------------------------------------
def _handle_generic(task: str, kind_hint: str, passes: int) -> str:
    """planning / writing / coding advice / general -> full looped answer."""
    result = looped_generate(task, passes=passes)
    return result.final


def _handle_research(task: str, passes: int) -> str:
    urls = notes.find_urls(task)
    if not urls:
        # No links -> produce a research plan instead of pretending to browse.
        plan = looped_generate(
            "Turn the following research request into a concrete research plan. "
            "List: (a) the key questions to answer, (b) what kinds of sources to "
            "look for, (c) search terms to try, (d) how to tell a good source from "
            "a bad one for this topic. Be specific to the topic.\n\n"
            f"REQUEST:\n{task}",
            passes=passes,
        ).final
        note = (
            "> Note: no URLs were included, so this is a research *plan*. Paste "
            "specific links into the task (or use the Project 3 research feed) and "
            "I'll read and summarise them for you.\n\n"
        )
        return note + plan

    # URLs present -> fetch and summarise them (grounded answer).
    fetched = []
    for u in urls[:5]:  # cap so one task can't fetch forever
        r = fetch_clean(u)
        if r.ok:
            fetched.append(f"### Source: {r.title or u}\n{r.url}\n\n{r.text[:6000]}")
        else:
            fetched.append(f"### Source: {u}\n(could not read this page: {r.error})")

    context = "\n\n---\n\n".join(fetched)
    answer = looped_generate(
        "Using ONLY the sources provided as context, answer the research request "
        "below. Cite which source each point comes from. If the sources don't "
        "cover something, say so rather than guessing.\n\n"
        f"REQUEST:\n{task}",
        context=context,
        passes=passes,
    ).final
    src_list = "\n".join(f"- {u}" for u in urls[:5])
    return f"{answer}\n\n---\n**Sources read:**\n{src_list}"


def _handle_email(task: str, passes: int) -> str:
    result = looped_generate(
        "The user wants help with an email. Produce two things:\n"
        "1. A suggested importance + category line: `Importance: high|normal|low "
        "| Category: <one word>`\n"
        "2. A ready-to-send draft reply in a natural, appropriate tone.\n"
        "Do not invent facts you weren't given; leave [brackets] for details the "
        "user must fill in.\n\n"
        f"EMAIL / REQUEST:\n{task}",
        passes=passes,
    ).final
    footer = (
        "\n\n---\n> This draft was written locally and **not sent**. To auto-label "
        "or triage real email, set up the Project 3 email automation."
    )
    return result + footer


# --------------------------------------------------------------------------
# Step 3: the public entry point
# --------------------------------------------------------------------------
def process_task(task: str, passes: int | None = None) -> dict:
    """
    Process a single task. Returns a dict with the category, the markdown
    output, and a suggested filename. Never raises for 'expected' problems --
    it returns an error string in `output` instead so the UI/batch job survives.
    """
    task = (task or "").strip()
    passes = passes if passes is not None else CFG["max_passes"]

    if not task:
        return {"category": "general", "output": "_(empty task)_", "title": "empty"}

    if not llm.ollama_up():
        return {
            "category": "error",
            "title": "ollama-offline",
            "output": (
                "**Ollama isn't running.** Start the Ollama app (or run "
                "`ollama serve`) and try again."
            ),
        }

    try:
        category = classify(task)

        if category == "research":
            output = _handle_research(task, passes)
        elif category == "email":
            output = _handle_email(task, passes)
        else:  # planning, writing, coding, general
            output = _handle_generic(task, category, passes)

        if category == "coding":
            output += (
                "\n\n---\n> Want the changes applied to a real repo? Use the "
                "OpenCode agent from Project 3 (it edits files locally via Ollama)."
            )

        title = notes.slugify(task.splitlines()[0], max_len=40)
        return {"category": category, "output": output, "title": title}

    except Exception as exc:  # noqa: BLE001 - keep the caller alive
        return {
            "category": "error",
            "title": "error",
            "output": f"Something went wrong while processing this task:\n\n`{exc}`",
        }


def save_result(task: str, result: dict) -> Path:
    """Write a result to the task-outbox as a dated markdown file."""
    stamp = notes.now_stamp()
    fname = f"{stamp}-{result['category']}-{result['title']}.md"
    outbox = Path(CFG["task_outbox"])
    outbox.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Task\n\n{task}\n\n"
        f"*Category: {result['category']}*\n\n"
        f"---\n\n{result['output']}\n"
    )
    target = outbox / fname
    target.write_text(body, encoding="utf-8")
    return target


if __name__ == "__main__":
    # CLI test:  python process.py "Plan a 3-day trip to Rome on a small budget"
    import json
    q = " ".join(sys.argv[1:]) or "Plan a relaxed weekend with two hours of deep work."
    llm.require_ollama()
    res = process_task(q)
    print(json.dumps({"category": res["category"], "title": res["title"]}, indent=2))
    print("\n" + res["output"])
