# daddys-home

One command that opens my whole workspace at once.

I got tired of starting every session the same way: open a terminal, cd somewhere, start a session, repeat four times, then spend ten minutes remembering what I was in the middle of. So I made a command that does all of it.

Type `daddyshome` and you get a boot sequence, a spoken greeting, and four terminal windows tiled across the screen in a 2x2 grid. Each one is already in the right directory. Two of them have already started briefing me on where things stand.

Named after the Iron Man scene. The voice leans that direction too.

## What it does

1. Prints a banner and a short diagnostic sequence
2. Speaks a greeting that changes based on the time of day
3. Runs your reports headlessly and builds one dashboard
4. Opens the dashboard and reads the summary out loud
5. Opens one terminal window per bay, tiled to fill the screen
6. Starts a session in each, optionally with a prompt already submitted

Bays that have a prompt come back with an answer waiting. Bays that do not are just a normal session sitting in the right folder.

## The briefing

Reports are defined in `~/.config/daddyshome/reports.conf`, same three field format as bays. Each one runs in its own directory, in parallel, before any window opens. The results become a single dashboard with charts, stat tiles and alerts, plus a short spoken summary that gets read to you while you look at it.

Reports have to answer with a strict JSON contract. Anything else and the report is marked unavailable rather than guessed at. Every prompt tells the model to report only what it actually read or ran, so a failed report says so instead of inventing numbers.

The briefing costs real tokens, roughly a dollar or two a run depending on how much your reports read. If you just want the windows:

```sh
daddyshome --no-brief
```

Or the report without the windows:

```sh
daddyshome --brief-only
```

### Permissions

A headless session cannot stop and ask you to approve a command, so anything a report needs has to be pre-approved in the `ALLOWED_TOOLS` list in `brief.py`. That list is deliberately read only: git inspection, file reading, and two helper scripts.

If a report needs something not on the list, write a small read only helper and allow that instead of widening the list. That is what `repo_survey.py` is. Surveying repos needs `cd repo && git log`, which is a compound command that no narrow permission pattern will match, and the alternative was allowing all of `git`, including `push` and `reset`. A helper script that only ever runs read only subcommands was the safer trade.

### The charts

Single hue, direct labelled, with a table view under each one. Status is never carried by colour alone: every alert ships a distinct glyph and a written level, because the warning and serious colours sit close enough in hue that a colourblind reader could not otherwise tell them apart. Light and dark are both selected rather than flipped.

## Install

```sh
git clone https://github.com/levimackay/daddys-home.git
cd daddys-home
./install.sh
```

That puts `daddyshome` in `~/.local/bin` and creates a starter config at `~/.config/daddyshome/bays.conf`.

Requires macOS, zsh, and Terminal.app. The tiling uses AppleScript, so it will not work in iTerm or Ghostty without changes.

## Configuring your bays

Everything lives in `~/.config/daddyshome/bays.conf`. The format is three fields separated by `::`

```
LABEL :: DIRECTORY :: PROMPT
```

Leave the prompt empty for a plain session:

```
PROJECT :: ~/code/my-project ::
```

Or give it a job to do before you even look at the window:

```
REVIEW :: ~/code/my-project :: Read the last 10 commits and tell me what looks risky.
```

Add a fifth bay and the grid becomes 3x2 on its own. The layout is computed from how many bays you have, so you never touch the geometry.

Run `daddyshome --edit` to open the file.

## Flags

| Flag | What it does |
|:--|:--|
| `--dry-run` | Shows every bay and the exact window coordinates without opening anything |
| `--quiet` | Skips the voice |
| `--no-brief` | Skips the reports, opens the bays straight away |
| `--brief-only` | Builds the dashboard and reads it, opens no bays |
| `--edit` | Opens the bay config |
| `--setup-mail` | Stores a Gmail app password in the Keychain |
| `--help` | Usage |

`--dry-run` is the one to use while you are setting up your bays.

## The inbox bay

One of my bays reads my email and tells me what actually needs a response. It uses IMAP with an app password, and it fetches with `BODY.PEEK` so nothing gets marked as read just because you looked at a summary.

Setup takes two steps.

Tell it which mailbox to read:

```sh
echo you@gmail.com > ~/.config/daddyshome/email
```

Then generate an app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) and store it:

```sh
daddyshome --setup-mail
```

That opens a fresh Terminal window and prompts you there. The password goes into the macOS Keychain. It never touches a file, a shell history, or this repo.

You can also run the fetcher on its own:

```sh
python3 ~/.local/share/daddyshome/inbox-brief/fetch_inbox.py --days 3
python3 ~/.local/share/daddyshome/inbox-brief/fetch_inbox.py --all --max 20
```

## A few things I ran into

If you paste an app password into a downloaded text file, check for a byte order mark. Three invisible bytes on the front of the file will fail the login with an error that tells you nothing useful.

`security add-generic-password -w` with no value needs a real terminal. If you run it somewhere without a TTY it will quietly store an empty password and act like it worked. That is why `--setup-mail` spawns its own window.

Terminal accepts exact pixel bounds without snapping to the character grid, which is the only reason the tiling lines up cleanly.

## Customizing the voice

```sh
export DADDYSHOME_VOICE=Daniel   # any voice from `say -v '?'`
export DADDYSHOME_RATE=172       # words per minute
export DADDYSHOME_GAP=8          # pixels between tiled windows
```

Daniel is the closest thing macOS ships to the voice I was going for. If you go to System Settings, then Accessibility, then Spoken Content, you can download the enhanced version of it. It is a noticeable upgrade and worth the two minutes.

## License

MIT

**Last updated:** 2026-08-07 07:33 PDT
