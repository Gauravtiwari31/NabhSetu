# APIx — SIH 2026 PS 26056 project document (LaTeX source)

Real-time Airfare Price Index for India. Full project document: problem framing,
index-number theory, formal index specification, data sources, system architecture,
USPs, delivery plan, references.

## Build

Needs a TeX Live install with `charter`, `helvet`, `tcolorbox`, `tabularx`, `booktabs`,
`xurl`, `fancyvrb`, `siunitx`.

```bash
pdflatex main.tex && pdflatex main.tex && pdflatex main.tex
```

Three passes (TOC + internal refs). Output: `main.pdf`, 49 pages.

## Files

```
main.tex                      preamble, colours, boxes, \input order
sections/00-title.tex         title page, how-to-read, TOC
sections/01-exec.tex          Part 1  executive summary + the reframe
sections/02-problem.tex       Part 2  CPI 2024 facts, institutional map, gap analysis
sections/03-theory.tex        Part 3  index-number theory
sections/04-apix.tex          Part 4  formal APIx specification
sections/05-data.tex          Part 5  sources, route basket, schema
sections/06-engineering.tex   Part 6  architecture, legal/ethical framework, stack
sections/07-usp.tex           Part 7  ten USPs
sections/08-delivery.tex      Part 8  plan, risks, judge Q&A
sections/09-refs.tex          Part 9  sourced references
```

## Custom macros (main.tex)

| Macro | Use |
|---|---|
| `\bhead{}` | bold sans run-in heading |
| `\code{}` | inline monospace |
| `\rt{}` | IATA code in small caps |
| `\refurl{}` | breakable URL in reference list |
| `keybox` | blue — key insight / do-this |
| `uspbox` | teal — USP claim |
| `warnbox` | amber — caveat / honest weakness |
| `redbox` | red — hard constraint / must-read |

## Before using this

Anything tagged **[VERIFY]** in the document is a value that moves and must be
re-pulled from the primary source before it is quoted. Two in particular:

1. Item-level CPI 2024 weight for passenger transport by air —
   <https://cpi.mospi.gov.in> (Announcements tab).
2. GST rates on domestic air travel by cabin.

Also re-check every URL in Part 9; government portals reorganise.
