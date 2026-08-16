"""Stack package — single source of truth for the Local AI Stack.

``stack.toml`` (repo root) is the one and only configuration file. Every
service, script and engine imports this package to get typed access to it.
Do NOT add parallel config files (no config.json, olympus.toml or
pipeline.toml). If a setting lives here it lives in ``stack.toml`` and is
read through :mod:`stack.config`.

Usage::

    from stack.config import cfg
    print(cfg.ollama.url)
"""