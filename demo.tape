Output demo.gif

Set FontSize 14
Set Width 120
Set Height 34
Set Theme "Dracula"
Set Padding 16
Set PlaybackSpeed 0.75
Set TypingSpeed 80ms
Set CursorBlink false

Sleep 500ms

Type "TERM=xterm-256color /Users/suhas/.local/bin/bloatr --dry-run"
Sleep 300ms
Enter

# Wait for Textual to boot, scan, and render
Sleep 12s

# Navigate down through the list
Down
Sleep 600ms
Down
Sleep 600ms
Down
Sleep 700ms

# Drill into a folder
Enter
Sleep 6s

# Browse children
Down
Sleep 500ms
Down
Sleep 600ms

# Go back
Escape
Sleep 1000ms

# Select three items
Space
Sleep 600ms
Down
Sleep 400ms
Space
Sleep 600ms
Down
Sleep 400ms
Space
Sleep 800ms

# Delete flow
Type "d"
Sleep 2000ms

# Cancel
Type "n"
Sleep 1000ms

# Quit
Type "q"
Sleep 800ms
