# Repository Guidelines

## Project Structure & Module Organization

This repository stores a Waybar configuration for a Hyprland desktop.

- `config.jsonc` defines bar placement, height, spacing, module order, and includes module settings.
- `modules.json` contains per-module Waybar configuration such as formats, tooltips, thresholds, and click actions.
- `style.css` contains all visual styling for the bar, module containers, workspace buttons, and custom modules.

There is no application source tree, build output, or asset directory. External scripts referenced by `on-click` commands should live outside this repository and must be checked before use.

## Build, Test, and Development Commands

There is no build step.

- `waybar --version` checks the installed Waybar version.
- `waybar -c config.jsonc -s style.css -l warning` starts Waybar with this configuration for manual validation.
- `git diff --check` checks for whitespace issues before committing.
- `rg "on-click|hwmon-path|battery#"` helps find machine-specific integrations that may need verification.

Avoid running commands that restart or kill desktop services unless the user explicitly approves it.

## Coding Style & Naming Conventions

Use 4-space indentation in JSONC and CSS. Keep module names aligned with Waybar conventions: built-in modules use their documented names, and custom modules use `custom/name`.

Keep comments short and in English. Do not add comments that merely repeat the setting name. Avoid adding new decorative symbols unless they are already part of the configured icon style.

Prefer clear, direct module formats, for example:

```jsonc
"cpu": {
    "format": "  {usage}%"
}
```

## Testing Guidelines

This repository has no automated test framework. Validate changes manually by starting Waybar with the local config and checking the rendered bar, hover states, module output, and click actions.

When editing hardware-specific modules, verify the referenced paths exist, such as `/sys/class/hwmon/...` or `/sys/class/power_supply/...`.

## Commit & Pull Request Guidelines

The current history only contains an initial commit, so no detailed convention is established. Use short imperative commit messages, for example `Update Waybar module styling`.

Pull requests should describe visible UI changes, list any changed modules, mention machine-specific assumptions, and include screenshots when styling changes are involved.

## Agent-Specific Instructions

Before editing, state the intended file changes and wait for confirmation. Use only read-only git commands unless explicitly asked otherwise.
