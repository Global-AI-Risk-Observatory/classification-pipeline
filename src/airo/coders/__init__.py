"""Automated coders: programs that take `tasks.jsonl` and `codebook.md` and return
one Label per passage, as JSONL, exactly like a human coder would.

Each coder lives in its own module and is run as a module entry point, e.g.
`python -m airo.coders.gemini`. Its output file is then accepted with
`python -m airo accept <file> --coder <name>` like any other coder's.
"""
