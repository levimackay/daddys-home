#!/bin/zsh
# Installs daddyshome into ~/.local/bin and sets up the config directory.

emulate -L zsh
set -e

SRC="${0:A:h}"
BIN="$HOME/.local/bin"
CFG="$HOME/.config/daddyshome"
SHARE="$HOME/.local/share/daddyshome"

mkdir -p "$BIN" "$CFG" "$SHARE"

install -m 755 "$SRC/daddyshome" "$BIN/daddyshome"
install -m 755 "$SRC/brief.py" "$SHARE/brief.py"
install -m 755 "$SRC/repo_survey.py" "$SHARE/repo_survey.py"
mkdir -p "$SHARE/inbox-brief"
install -m 755 "$SRC/inbox-brief/fetch_inbox.py" "$SHARE/inbox-brief/fetch_inbox.py"

for name in bays reports; do
  if [[ -f "$CFG/$name.conf" ]]; then
    print "Kept your existing $CFG/$name.conf"
  else
    install -m 644 "$SRC/$name.conf.example" "$CFG/$name.conf"
    print "Created $CFG/$name.conf from the example. Edit it before first use."
  fi
done

print ""
print "Installed daddyshome to $BIN/daddyshome"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) print ""
     print "$BIN is not on your PATH. Add this to your ~/.zshrc:"
     print "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

print ""
print "Next:"
print "  daddyshome --edit         set up your bays"
print "  daddyshome --dry-run      check it without opening anything"
print "  daddyshome                launch"
print ""
print "For the inbox bay, also run:"
print "  echo you@gmail.com > $CFG/email"
print "  daddyshome --setup-mail"
