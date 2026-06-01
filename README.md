# Zyra

Zyra is a lightweight, interpreted Telegram Bot DSL (Domain Specific Language). It allows developers to create powerful Telegram bots using a simple, human-readable `.zy` syntax.

## Installation

### Lightweight (Core)
Perfect for Android/Termux and minimal environments.
```bash
pip install zyra-lang
```

### Full (with AI and Watch mode)
```bash
pip install "zyra-lang[ai,watch]"
```

## Quick Start

Create a new bot:

```bash
zyra new mybot
cd mybot
```

Run your bot directly:

```bash
zyra main.zy
```

Watch mode (requires `zyra[watch]`):

```bash
zyra watch main.zy
```

## Syntax Guide

### Basic Setup
```zyra
bot "MyBot"
token env("BOT_TOKEN")
```

### Commands
```zyra
command "/start" {
    reply "Welcome to Zyra!"
}
```

### Function Calls
Zyra supports modern function call syntax with positional and named arguments.

```zyra
on command "/start" {
    // New function syntax
    reply("Welcome to Zyra!")
    
    // Support for named arguments
    reply("<b>Bold text</b>", mode="HTML")
    
    // Multiple arguments
    send(user.id, "Hello from Zyra")
}

// User-defined functions with named arguments
fn reward(uid, amount) {
    reply("User ${uid} rewarded with ${amount}")
}

on command "/reward" {
    reward(user.id, amount=10)
}
```

**Backward Compatibility:**
Old syntax still works perfectly:
```zyra
reply "Traditional style"
send user.id "Traditional send"
```

### Control Flow
Zyra supports block and one-line if/elif/else syntax.

```zyra
on command "/start" {
    // One-line if
    if referrer => reply("Invited by ${referrer}")

    // Complex if-elif-else chain
    if user.id == 123 {
        reply("Hello Owner")
    }
    elif user.id == 456 => reply("Hello Admin")
    else {
        reply("Hello User")
    }
}
```

    else {
        reply("Hello User")
    }
}
```

### Buttons
Zyra makes Telegram buttons simple and readable.

#### Reply Keyboard
```zyra
on command "/start" {
    reply("Choose an option:", buttons=[["Profile"], ["Wallet"]])
}
```

#### Inline Buttons & Callbacks
```zyra
on command "/menu" {
    reply("Menu:", inline=[
        ["Profile", "profile"],
        ["Join Channel", url="https://t.me/example"]
    ])
}

on callback "profile" => reply("Your Profile")
```

#### Alerts & Notifications
Feedback for callback buttons:
```zyra
on callback "update" {
    alert("Profile updated!", mode="silent") // Small top notification
}

on callback "withdraw" {
    alert("Insufficient funds!", mode="alert") // Centered popup dialog
}
```

#### Multi-row Layout
```zyra
reply("Multi-row:", inline=[
    [["Row 1 - A", "a"], ["Row 1 - B", "b"]],
    [["Row 2 - C", "c"]]
])
```

### Databases (SQLite)
```zyra
table Users {
    id integer primary
    name text
}

command "/register" {
    insert Users {
        id = user.id
        name = user.first_name
    }
    reply "Registered!"
}
```

### Referral System
Zyra has a first-class referral system. It automatically parses Telegram start payloads (e.g., `/start 12345`).

```zyra
on command "/start" {
    if referrer {
        // User joined via referral link
        send(referrer) "Someone joined using your link!"
        reply "Welcome! You were referred by ${referrer}"
    } else {
        reply "Welcome! You joined directly."
    }
}
```

**Features:**
- **Automatic Parsing**: Extracts IDs from `/start <payload>`.
- **Validation**: Payload must be an **integer** and exactly **10 characters** long.
- **Built-in Variables**: Access via `referrer` or `user.referrer`.
- **Truthiness**: `if referrer` works for null-checking.
- **Null Comparison**: `if referrer == null` or `if referrer != null`.
- **Self-referral Protection**: Users cannot refer themselves.

### AI Features (requires `zyra[ai]`)
```zyra
ai {
    provider "openai"
    model "gpt-4"
}

command "/ask" {
    ai_reply message.text
}
```

## Architecture

`.zy source` -> **Lexer** -> **Parser** -> **AST** -> **Interpreter (Runtime)**

Zyra executes your script directly without generating intermediate Python files, keeping your project clean and fast.
