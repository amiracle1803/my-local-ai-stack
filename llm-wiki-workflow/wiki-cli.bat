@echo off
:: wiki-cli.bat — Mechanical wiki tooling (no API key required)
::
:: Usage:
::   wiki-cli index                         Rebuild wiki/index.md
::   wiki-cli lint                          Health check (links, dates, orphans)
::   wiki-cli new concept <slug> --title "X"
::   wiki-cli new entity  <slug> --title "X"
::   wiki-cli new source  <slug> --title "X"
::   wiki-cli new comparison <slug> --title "X"
::   wiki-cli search "term"
::   wiki-cli log ingest "Title" --note "..."
::
python "%~dp0tools\wiki.py" %*
