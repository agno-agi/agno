# Tutorial parity

Source: `content/docs/first-agent/index.mdx`, read from the live local docs checkout
on 2026-09-16, including working changes.

- Full input SHA-256: `c8cabe1bdb4112583ff0d44090f51b0dda653b3e2d69203f5bc4d7f6fd39ace0`
- Extracted Python SHA-256: `48504a3e6e2e349ea0528a6c4c157e21857aecb3a1ab86abd5fabee11c093d97`
- Cookbook file: byte-for-byte equal to the Python fence, with a final newline.
  No code or prompt differences. The demo retains the exact three tutorial prompts.
  The tutorial takes precedence over cookbook banner/docstring conventions for
  this downloadable file.

The README uses `uv venv --python 3.14` and `uv pip install -r requirements.txt`
to keep this directory easy to download. The tutorial's `uv init` / `uv add`
workflow installs the same required packages. Slack and Railway are later steps;
the starter remains independent of their dependencies and credentials.
