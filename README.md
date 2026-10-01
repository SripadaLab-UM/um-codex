# UM-Codex

Full-power OpenAI Codex on U-M GPT Toolkit, running in a Docker container on
your Mac or Windows computer. At each launch you choose which folders Codex
can read, which it can change, and whether it can use the internet; then
Codex opens in your terminal.

Status: under construction (see [docs/DESIGN.md](docs/DESIGN.md)).

You need a U-M GPT Toolkit API key for Codex (see ITS's "Codex Setup"
articles for how to get one). The key is kept in your computer's keychain and
never goes into the container.

## Run from source (M1, a Mac with Docker Desktop)

You need [uv](https://docs.astral.sh/uv/), Docker Desktop (running), and git.

1. Build the agent image locally (it isn't published yet). It's in
   `images/agent`, on the `m1-image` branch until that's merged:

   ```sh
   docker build -t um-codex-agent:dev path/to/a/checkout/of/m1-image/images/agent
   ```

2. In this repository:

   ```sh
   uv sync
   uv run um-codex pull      # the gateway image; the :dev agent image is skipped
   uv run um-codex key       # paste your Toolkit API key (saved in the Keychain)
   uv run um-codex doctor    # checks Docker, the images, the key and the Toolkit
   uv run um-codex           # choose a setup, then Codex opens
   ```

`um-codex` asks which folder Codex works in, which more folders it can
write, which it can only read, whether the internet is on, the model and the
approvals, then shows a summary and asks "Start?". When you quit Codex, the
container is removed; the setup's Codex history is kept (`codex resume`
works next time, or `uv run um-codex launch -- resume`).

Other commands: `uv run um-codex setups` (list, edit, delete setups) and
`uv run um-codex uninstall`.

For development only:
- `UMCODEX_DATA_DIR` puts UM-Codex's data folder somewhere else;
- `UMCODEX_AGENT_IMAGE` uses another agent image;
- `UMCODEX_UPSTREAM` sends model requests to a local stub instead of the
  Toolkit (UM-Codex says so when it's set).

Checks: `uv run ruff check . && uv run pyright && uv run pytest -q`.
