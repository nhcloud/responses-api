#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
selection=both
check=false
for argument in "$@"; do
    case "$argument" in
        dotnet|python|both) selection="$argument" ;;
        --check) check=true ;;
        *) echo "Usage: bash start.sh [dotnet|python|both] [--check]" >&2; exit 1 ;;
    esac
done

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
        cd -- "$root"
        MSYS_NO_PATHCONV=1 cmd.exe /d /c start.cmd "$@"
        exit $?
        ;;
esac

if [[ "$selection" != dotnet ]]; then
    python="$root/python/.venv/bin/python"
    if [[ ! -x "$python" ]]; then
        python="$root/.venv/bin/python"
    fi
    if [[ ! -x "$python" ]]; then
        echo "Missing Python virtual environment. Follow the README Python Setup steps first." >&2
        exit 1
    fi
fi
if [[ "$selection" != python ]] && ! command -v dotnet >/dev/null 2>&1; then
    echo "Missing dotnet. Install the .NET 10 SDK first." >&2
    exit 1
fi
export DOTNET_ENVIRONMENT="${DOTNET_ENVIRONMENT:-Development}"

terminal=""
if [[ "$(uname -s)" == Darwin ]]; then
    terminal=osascript
else
    for candidate in gnome-terminal konsole xfce4-terminal xterm; do
        if command -v "$candidate" >/dev/null 2>&1; then
            terminal="$candidate"
            break
        fi
    done
    if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        echo "A desktop session is required. In a headless shell, run each demo in its own terminal using the README commands." >&2
        exit 1
    fi
fi
if [[ -z "$terminal" ]] || ! command -v "$terminal" >/dev/null 2>&1; then
    echo "No supported terminal found. Use Terminal on macOS or gnome-terminal, konsole, xfce4-terminal, or xterm on Linux." >&2
    exit 1
fi
if [[ "$check" == true ]]; then
    echo "Prerequisites found. Ready to open selected demo terminals: $selection."
    exit 0
fi

launch() {
    local title="$1" command_text prefix
    shift
    printf -v prefix 'cd -- %q && ' "$root"
    printf -v command_text '%q ' "$@"
    command_text="${prefix}${command_text}; printf '\\nDemo ended. Press Enter to close.'; read -r"
    case "$terminal" in
        osascript)
            printf -v prefix 'export PATH=%q DOTNET_ENVIRONMENT=%q; ' "$PATH" "$DOTNET_ENVIRONMENT"
            command_text="${prefix}${command_text}"
            osascript - "$command_text" <<'APPLESCRIPT'
on run arguments
    tell application "Terminal"
        activate
        do script (item 1 of arguments)
    end tell
end run
APPLESCRIPT
            ;;
        gnome-terminal) gnome-terminal --title="$title" -- bash -c "$command_text" ;;
        konsole) konsole --new-window -p "tabtitle=$title" -e bash -c "$command_text" & ;;
        xfce4-terminal) xfce4-terminal --title="$title" --execute bash -c "$command_text" ;;
        xterm) xterm -T "$title" -e bash -c "$command_text" & ;;
    esac
}

if [[ "$selection" != dotnet ]]; then
    launch "Python demo" "$python" "$root/python/loop/loop_demo.py"
fi
if [[ "$selection" != python ]]; then
    launch ".NET demo" dotnet run --project "$root/dotnet/loop"
fi
echo "Opened selected demo terminals: $selection. Select 4 in each menu to exit its demo."