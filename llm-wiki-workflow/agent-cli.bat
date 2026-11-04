@echo off
:: agent-cli.bat — LLM-powered wiki agent
::
:: Usage:
::   agent-cli ingest raw/articles/my-article.md
::   agent-cli query "What is attention?"
::   agent-cli query "Compare A and B" --save
::   agent-cli lint
::
:: Requires ANTHROPIC_API_KEY in your environment.
::
python "%~dp0tools\agent.py" %*
