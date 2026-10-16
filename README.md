# Chaoxingstudy Copy-Disabled Simulated Keyboard Input Solution

A small Windows utility that sends text character by character as keyboard input for authorized scenarios where an input field does not support pasting.

## Run

Requires Windows and Python 3:

```powershell
py .\\keyboard_typer.py
```

## Usage

1. Enter text and set the startup delay and character interval.
2. Click `Start Typing`, then switch to the target input field during the countdown.
3. The tool sends the text character by character. Press `F8` or click `Stop` to interrupt it.

The tool does not read from or modify the clipboard. Use it only in windows where you are authorized to enter the text. Some applications may block simulated input.
