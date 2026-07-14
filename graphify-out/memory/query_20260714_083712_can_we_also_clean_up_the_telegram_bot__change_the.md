---
type: "query"
date: "2026-07-14T08:37:12.780330+00:00"
question: "can we also clean up the telegram bot? change the comands so its easier to do, having to do /something x isnt practical because i have to manually write all the line"
contributor: "graphify"
outcome: "useful"
source_nodes: ["telegram_remote.py", "handle_command", "tg_send"]
---

# Q: can we also clean up the telegram bot? change the comands so its easier to do, having to do /something x isnt practical because i have to manually write all the line

## Answer

Expanded from original query via graph vocab: [telegram, command, commands, callback, botones, bot, status, prop, audit, remote]. The Telegram control is centralized in tools/telegram_remote.py and tools/tg_send.py. Implemented a persistent one-tap read-only keyboard in tools/tg_menu.py, translated friendly labels and dedicated shortcuts to existing handlers, retained explicit commands for state-changing actions, and verified 241 tests.

## Outcome

- Signal: useful

## Source Nodes

- telegram_remote.py
- handle_command
- tg_send