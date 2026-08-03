# daddys-home

One command that opens my whole workspace at once.

I got tired of starting every session the same way: open a terminal, cd somewhere, start a session, repeat four times, then spend ten minutes remembering what I was in the middle of. So I made a command that does all of it.

Type `daddyshome` and you get a boot sequence, a spoken greeting, and four terminal windows tiled across the screen in a 2x2 grid. Each one is already in the right directory. Two of them have already started briefing me on where things stand.

Named after the Iron Man scene. The voice leans that direction too.

## What it does

1. Prints a banner and a short diagnostic sequence
2. Speaks a greeting that changes based on the time of day
3. Reads your bay list from a config file
4. Opens one terminal window per bay, tiled to fill the screen
5. Starts a session in each, optionally with a prompt already submitted

Bays that have a prompt come back with an answer waiting. Bays that do not are just a normal session sitting in the right folder.

## Install

```sh
git clone https://github.com/levibmackay/daddys-home.git
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
