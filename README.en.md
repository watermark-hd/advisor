# Advisor

## 🇯🇵 [日本語版はこちらから読めます →](README.md)

<img src="launcher/advisor.png" alt="Advisor" width="120">

*A lightweight AI agent for old High Sierra-era Macs*

**Advisor** brings old Intel Macs (Snow Leopard through High Sierra) back to
life as a genuinely useful AI agent — a lightweight terminal and GUI app that
works with both Claude (Anthropic) and Gemini (Google).

The command is called `advisor` on purpose — a neutral name so you don't have
to think about which AI is actually answering.

## Why I built this

It started with an old MacBook I'd mostly stopped using. At first I assumed
today's coding agents just wouldn't run on such an old setup — High Sierra
can only install VSCode up to version 1.85, after all. That turned out to be
a misconception; some agents do work there.

But even if they did, AI API costs add up fast, and I wanted something I
could use on an old Mac without worrying about the bill every time I typed
a question.

The real goal was always two things. First, I wanted something like a casual
conversation partner — a bit like an exchange diary, something easygoing I
could talk to without much ceremony. Second, since it's AI anyway, I wanted
to be able to drop into a terminal and get real coding help — reading files,
running commands, the works. **Advisor is built to show both faces: a gentle
conversation partner, and a sharp, no-nonsense AI.** That's why the GUI has
three themes — Note, Coding, and Hacker — so you can move between those two
faces depending on your mood.

## Who this is for

- Anyone with a 2010s-era Mac gathering dust in a drawer who wants to give it
  one more job
- People who want a slightly-more-human AI to chat or journal with, in a
  ruled-notebook-style screen rather than a sterile chat box
- People who just want quick terminal-based coding help — file edits, shell
  commands, without switching to a full IDE
- Anyone who wants to avoid pricey subscriptions or metered API bills —
  Gemini's free tier alone is enough to get going
- Anyone sharing a Mac with family who wants their own conversations kept
  private (encrypted history)
- Anyone who wants to hand this to English-speaking friends too — it follows
  the OS language setting automatically

## Features

- **Lightweight, almost no external dependencies** — the agent itself
  (`agent/claude-agent.pl`) is a single Perl file with zero CPAN
  dependencies. The GUI uses only Python's bundled `tkinter`.
- **Switch between two AIs anytime** — Claude (Anthropic) and Gemini
  (Google). Gemini has a free tier, so you can try the whole thing at
  zero cost.
- **Three GUI themes: Note, Coding, and Hacker** — a ruled-notebook-style
  chat screen, a green-on-black hacker terminal look, whatever matches
  your mood.
- **Also works as a plain terminal command** — just run `advisor`, no GUI
  required.
- **Conversation history is encrypted and stored locally** — unreadable
  to anyone who doesn't know your passphrase.
- **Automatic Japanese/English switching** — the GUI, terminal text, and
  even the native macOS menu bar all follow your Mac's system language
  automatically.
- **Double-clickable `Advisor.app`** — no terminal experience required.
  Drop it in the Dock and you're one click away every time.

## Supported OS tiers

- **Tier B: Mavericks (10.9) through High Sierra (10.13) and later** — the
  system `curl` already supports TLS 1.2, so no extra build step is needed.
  This is the tier that's implemented today.
- **Tier A: Snow Leopard through Mountain Lion (10.6–10.8)** — the system
  `curl` doesn't even reach TLS 1.0, so OpenSSL/curl need to be built
  (fetch source on a modern machine → transfer to the target → build
  locally on the target). Not started yet — next step.

## Setup (Tier B: High Sierra and similar)

```bash
bash setup.sh
```

This walks you through choosing an AI (Gemini or Anthropic), getting and
saving an API key, installing the `advisor` command, setting up bash
completion, building the double-clickable `Advisor.app`, and checking that
the API actually responds — all in one pass. Once it's done, open a new
Terminal window (or run `source ~/.bash_profile`) and just type `advisor`.

> `Advisor.app` is built with [py2app](https://py2app.readthedocs.io/). The
> first run automatically installs Xcode Command Line Tools (needed for code
> signing, ~190MB, one-time), py2app itself, and
> [pyobjc](https://pyobjc.readthedocs.io/) (~7MB, used to localize the native
> macOS menu bar). If that build fails for any reason, setup falls back to a
> simpler app bundle automatically, so the `advisor` command always ends up
> working either way.

## Using the GUI

Double-click `Advisor.app`, or run `advisor gui` — either way, the GUI opens
directly with no terminal window.

- The **[ Chat ] [ Command ]** tabs at the top switch between the AI
  conversation screen and a shell command panel.
- Three visual themes are available: **Note** (a ruled, handwritten-notebook
  look), **Coding**, and **Hacker** (green on black). Switch anytime from
  **[ Theme ]** in the header.
- **[ Switch AI ]** lets you pick a Claude or Gemini model, and
  **[ Resume ]** reopens an encrypted past conversation.
- The text box uses your Mac's normal input method directly, sidestepping
  Terminal.app's double-byte character quirks.

## Using the terminal (`advisor` command)

The agent itself (`agent/claude-agent.pl`) stays a simple conversation loop
on purpose — option parsing and the model-picker menu live in the generated
`~/bin/advisor` bash wrapper instead.

**The basics:**

```
advisor            start it
(pick a number from the list)    switch which AI you're talking to
type your question                get an answer
exit                               quit
```

You choose the AI once during `setup.sh`. After that, switching is just
**typing a number from the list**:

```
  1) Claude Opus 5 — best quality, paid
  2) Claude Sonnet 5 — balanced, paid
  3) Claude Haiku 4.5 — fast, paid
  4) Gemini Flash-Lite — fast, free   ← current
  5) Gemini Flash — high quality, free
Type a number to switch. Or just ask your question directly.

What can I help with> 3        ← this alone switches to Haiku
```

Available mid-conversation:

| Type this | What happens |
|---|---|
| `1`–`5` (a number) | switch to that AI (provider switches automatically too, and it's remembered next time) |
| `/model` or `?` | show the AI list again |
| `/claude` / `/gemini` | switch provider only |
| `exit` / Ctrl-D | quit |

Shell-level options (only when you need them):

```
advisor --select-model [number]  choose which AI from the shell
advisor --list-models            list available AIs
advisor -m <ID>                  use a different AI for this session only
advisor --list-history           list saved conversations
advisor --resume                 continue a saved conversation
advisor --no-history             don't save this session
advisor --change-passphrase      change the history passphrase
advisor --set-recovery           set a recovery passphrase
advisor -h / --version           help / version
```

In a new terminal, type `advisor ` and press Tab to complete option names;
after `advisor -m `, Tab completes available model IDs
(`completion/advisor-completion.bash`, tested against bash 3.2, the version
that ships with High Sierra).

- See the list again anytime with **`/model`** (or `?`).
- Picking a number also switches the underlying provider (Claude/Gemini)
  automatically, and it's saved to `~/.claude-agent-env` for next time. If
  you haven't saved a key for that AI yet, you'll be prompted to paste one
  right there.
- To switch just the provider, use **`/claude`** / **`/gemini`**.
- Gemini tends to "think" for a while even on simple questions, so thinking
  is set shallow (`LOW`) by default. Set `CLAUDE_GEMINI_THINKING=high` if you
  want it to think harder.

## About the Japanese/English support

Advisor checks your Mac's system language (`defaults read -g AppleLocale`)
and automatically switches the GUI, terminal text, `setup.sh` prompts, and
even the native macOS menu bar between Japanese and English. You can also
force a language with the `CLAUDE_LANG=en` (or `ja`) environment variable.

## Conversation history (encrypted, stored locally)

By default, conversations are saved encrypted to
`~/.claude-agent/history/<timestamp>.json.enc`. Even if you share one Mac
with family, nobody without your passphrase can read them.

### How it works

- Each conversation file is encrypted with a random **master key**, and that
  master key itself is wrapped with your **passphrase** (and, optionally, a
  **recovery phrase**) into `key.enc` / `key.recovery.enc`. Either one can
  unwrap the master key, so forgetting your passphrase doesn't mean losing
  everything if you set a recovery phrase.
- Encryption is done by shelling out to `openssl enc -aes-256-cbc` (works
  fine against the LibreSSL that ships with High Sierra). Secrets are passed
  to openssl via environment variables — never through `ps` output, the
  command line, or disk.
- High Sierra's LibreSSL doesn't support `-pbkdf2`, so key derivation falls
  back to MD5-based, which is weaker than modern KDFs — but still far safer
  than storing history in plain text.

### Using it

- The first time you run it, you'll set a passphrase (typed twice), and
  optionally a recovery phrase (a secret question) right after. From then
  on, you're asked for the passphrase once per launch (hidden as you type).
  There's no retry limit — mistype as many times as you need. Pressing
  Enter with nothing typed starts that session without saving history.
- Forgot your passphrase? Type `r` at the prompt to recover via your
  recovery phrase (only works if you set one). You can set a new passphrase
  right after recovering. Recovery answers ignore case and extra
  leading/trailing/repeated whitespace.
- `advisor --resume` picks up your last conversation; `advisor
  --list-history` lists everything saved.
- `advisor --change-passphrase` changes your passphrase, and `advisor
  --set-recovery` sets or changes the recovery phrase — both just re-wrap
  the master key, so your existing history is untouched.
- `advisor --no-history` (or `CLAUDE_NO_HISTORY=1`) disables saving for that
  session — you won't be asked for a passphrase at all.
- **If you forget both your passphrase and your recovery phrase, everything
  saved so far becomes unreadable.** To start over, delete
  `~/.claude-agent/history/` and set things up again.

> Note: a guessable recovery answer (like "your first car") is the weakest
> link in this whole scheme. Pick something as non-obvious as a real
> password, or go in knowing that trade-off.

## About the agent (`agent/claude-agent.pl`)

- Single file, zero external CPAN dependencies
- Hand-rolled JSON encode/decode (recursive-descent parser)
- Four tools: `read_file` / `write_file` / `list_dir` / `run_shell` (writes
  and shell execution prompt for confirmation)
- Conversation history is always kept internally in Anthropic's content-block
  format, converting to Gemini's `contents`/`parts` format only right before
  and after each Gemini API call — tool execution and input handling code
  never has to think about which provider is active
- Handles Gemini 3's `thoughtSignature` requirement (must be re-attached when
  sending a functionCall back, or the API returns a 400)
- HTTP is done by shelling out to `curl` as a subprocess (keeps TLS handling
  out of Perl entirely)
- History encryption shells out to `openssl` (see above)
- The `CLAUDE_CURL` / `CLAUDE_CACERT` environment variables let you swap in a
  self-built toolchain for Tier A machines (`setup.sh` automatically prefers
  `~/claude-toolchain` if it exists)

## About billing

This repository itself is free to use, but you'll need your own API key to
actually talk to either AI. No API key is included in the code anywhere.

- **Gemini**: get a key at
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey) with any
  Google account — the free tier (no card required) is enough to get
  started comfortably.
- **Anthropic**: get a key at
  [console.anthropic.com](https://console.anthropic.com/) and add a small
  credit charge under Billing (this is separate, pay-as-you-go billing —
  not the same as a claude.ai Pro/Max subscription).

## License

[MIT License](LICENSE)
