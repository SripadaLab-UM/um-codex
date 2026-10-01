# UM-Codex app test: login shells (the Codex app runs `$SHELL -l -i -c`)
# get what the image's ENV gives `docker exec`. Without CODEX_HOME the app's
# app-server would use ~/.codex and ignore UM-Codex's config.toml.
export CODEX_HOME=/codex-home
case ":$PATH:" in *:/opt/venv/bin:*) ;; *) PATH="/opt/venv/bin:$PATH" ;; esac
case ":$PATH:" in *:/usr/local/bin:*) ;; *) PATH="/usr/local/bin:$PATH" ;; esac
export PATH
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export MPLCONFIGDIR=/tmp/matplotlib R_LIBS_USER=/home/agent/R/library
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
