---
name: officecli
description: 使用内置 officecli-win-x64.exe 读取、创建和修改 Word (.docx)、Excel (.xlsx)、PowerPoint (.pptx) 文档；支持结构查看、查询、DOM 编辑、批量操作和校验，无需安装 Office。
---

# OfficeCLI

Use this skill whenever the user asks you to create, read, inspect, edit, format, or validate a Word (`.docx`), Excel (`.xlsx`), or PowerPoint (`.pptx`) document.

## Bundled executable

The Windows binary is an attachment of this skill:

`.agents/skills/officecli/officecli-win-x64.exe`

- Invoke it through the `RunCli` tool. Set `command` to the path above (relative to the project root) and `args` to the argument list.
- Do **not** build a shell command string. Pass each argument separately:
  `RunCli(command=".agents/skills/officecli/officecli-win-x64.exe", args=["view", "report.docx", "outline"])`.
- Brackets in paths such as `/slide[1]` are safe when passed as separate `args`; shell quoting is not needed.
- If the agent is not running from the project root, use the absolute path to this binary inside the skill directory.

## Detailed reference (load on demand)

The complete command reference is bundled at:

`references/officecli-reference.md`

Load it only when you need detailed property names, element types, or advanced features:

`loadSkill(name="officecli", filename="references/officecli-reference.md")`

For ordinary work, prefer `officecli help ...` because it is faster and always matches the installed binary.

## Always check help instead of guessing

When unsure about property names, value formats, or command syntax, run help first. One help query is faster than guess-fail-retry loops.

```text
officecli help
officecli help docx
officecli help docx paragraph
officecli help docx set paragraph
officecli help docx paragraph --json
```

Format aliases: `word` -> `docx`, `excel` -> `xlsx`, `ppt` / `powerpoint` -> `pptx`.
Verbs: `add`, `set`, `get`, `query`, `remove`.

## Core strategy

Use the highest layer that can express the task:

1. **L1 read**: `create`, `view`, `get`, `query`, `validate`.
2. **L2 DOM editing**: `set`, `add`, `move`, `swap`, `remove`, `batch`.
3. **L3 raw XML**: `raw`, `raw-set`, `add-part` only when L2 cannot express the change.

Add `--json` when you need structured output for parsing or follow-up decisions.

## Recommended workflow

1. Determine the target file path and format from the user's request.
2. If the file does not exist, create it:
   `officecli create <file.docx|file.xlsx|file.pptx>`
3. Inspect before editing:
   `officecli view <file> outline`
   `officecli view <file> text`
   `officecli get <file> <path> --depth N --json`
4. Edit with DOM operations:
   `officecli set <file> <path> --prop key=value ...`
   `officecli add <file> <parent> --type <type> --prop key=value ...`
5. Validate and review:
   `officecli validate <file>`
   `officecli view <file> issues`
6. Before a non-officecli program or a human opens the file, flush changes:
   `officecli save <file>` or `officecli close <file>`.

## Quick start

Word:

```text
officecli create report.docx
officecli add report.docx /body --type paragraph --prop text="Executive Summary" --prop style=Heading1
officecli add report.docx /body --type paragraph --prop text="Revenue increased by 25% year-over-year."
```

Excel:

```text
officecli create data.xlsx
officecli set data.xlsx /Sheet1/A1 --prop value="Name" --prop bold=true
officecli set data.xlsx /Sheet1/A2 --prop value="Alice"
```

PowerPoint:

```text
officecli create slides.pptx
officecli add slides.pptx / --type slide --prop title="Q4 Report" --prop background=1A1A2E
officecli add slides.pptx "/slide[1]" --type shape --prop text="Revenue grew 25%" --prop x=2cm --prop y=5cm --prop font=Arial --prop size=24 --prop color=FFFFFF
```

When calling through `RunCli`, translate the arguments after the executable into the `args` list, for example:

```text
RunCli(command=".agents/skills/officecli/officecli-win-x64.exe",
       args=["set", "data.xlsx", "/Sheet1/A1", "--prop", "value=Name", "--prop", "bold=true"])
```

## Essential commands

```text
officecli create <file>                 Create a blank .docx/.xlsx/.pptx (type comes from the extension)
officecli open <file>                   Keep the file resident for a longer editing session
officecli close <file>                  Flush changes and release the file
officecli save <file>                   Flush changes but keep the file resident
officecli view <file> <mode>            outline | stats | issues | text | annotated | html | screenshot | svg | pdf | forms
officecli get <file> <path> --depth N   Read a node and its children; add --json for structured output
officecli query <file> <selector>       CSS-like query, e.g. 'shape[fill=FF0000]'
officecli set <file> <path> --prop ...  Modify properties of an existing element
officecli add <file> <parent> --type ... --prop ...
officecli remove <file> <path>
officecli move <file> <path> --to <parent> [--index N] [--after <path>] [--before <path>]
officecli swap <file> <path1> <path2>
officecli validate <file>               Validate against the OpenXML schema
officecli dump <file> [<path>]          Emit a replayable batch JSON for round-trip work
officecli batch <file> --input <json>   Apply multiple operations atomically
officecli raw <file> <part>             Read raw XML
officecli raw-set <file> <part> --xpath "..." --action replace --xml "..."
```

## Resident mode

Every command auto-starts a resident process (60 second idle timeout), so normal commands already see the latest edits. Explicit `open` / `close` is useful for longer sessions (12 minute idle timeout). Close the file in Word, Excel, PowerPoint, or WPS before modifying it with officecli.

## Important rules and pitfalls

- Paths are **1-based** (`/body/p[3]` is the third paragraph). `--index` is **0-based**, except Excel `add --type row|col`, where it is 1-based.
- All element attributes go through `--prop`. Do not use `--name "foo"`; use `--prop name="foo"`.
- Do not guess property names. Run `officecli help <format> <element>`.
- In PowerPoint, `shape[1]` is usually the title placeholder; content shapes normally start at `shape[2]`.
- Use stable `@id=` / `@name=` paths when editing across multiple steps, because positional indices shift after insert/delete.
- Use `--json` when you need to parse results or decide the next action.
- No match during find/replace is a silent success; check `--json` output for the match count.
- After modifications, run `validate` and/or `view issues`.
- Use single quotes around text containing `$` in a shell; through `RunCli` pass the literal value as one argument.

## Specialized built-in skills

The binary can print scenario-specific guidance with `officecli load_skill <name>`. This is different from the agent's own `loadSkill` tool.

- Word: `word`, `academic-paper`
- PowerPoint: `pptx`, `pitch-deck`, `morph-ppt`, `morph-ppt-3d`
- Excel: `excel`, `financial-model`, `data-dashboard`

Pick the most specific match and load one skill per artifact. For example, a fundraising deck should use `officecli load_skill pitch-deck`.
