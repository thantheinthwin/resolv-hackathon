# Team Activity for Codex

Team members and their agents publish their name, agent label, branch, task and intended files or directories to a single coordinator for this repository. Every client sees the same live leases. Overlapping claims are rejected atomically, including parent and child directory claims. Comparisons fold case to accommodate different filesystems. A disconnected agent's lease expires after 15 minutes.

## Start the coordinator once

On a team-controlled machine with Python 3.12, install the existing API requirements and start the coordinator from the repository root. Provide a random team credential of at least 32 bytes through the server's environment or secret manager. Share the credential privately with the three teammates. `TEAM_ACTIVITY_DB` can point at a durable SQLite file and defaults to `data/team-activity.sqlite3`. Keep this database on the server's local disk.

```sh
python -m pip install -r api/requirements.txt
python -m uvicorn coordinator:create_app --factory --app-dir plugins/team-activity --host 127.0.0.1 --port 8765
```

The server reads `TEAM_ACTIVITY_TOKEN` at startup. For another laptop, forward local port 8765 to the coordinator with an SSH tunnel. Alternatively the team can operate an authenticated HTTPS endpoint terminating at the loopback service. Each participant uses the **same coordinator**. A separate local server per laptop would create independent claim sets.

## Install and use the plugin

On each teammate's device, use a Codex CLI with the `plugin` command. Register this repository's marketplace and install Team Activity. Before merge, install from a checkout of this branch using the local path shown here. After merge, the marketplace source can also be `thantheinthwin/resolv-hackathon`.

```sh
codex plugin marketplace add /absolute/path/to/resolv-hackathon
codex plugin add team-activity@resolv-team
```

Set `TEAM_ACTIVITY_URL` (for example `http://127.0.0.1:8765` through the tunnel) and `TEAM_ACTIVITY_TOKEN` in the environment inherited by the agent. Open a new Codex session and invoke the **Team Activity** plugin: “Claim the API startup fix for Thant before editing and show me concurrent work.” The bundled skill handles listing, claiming, heartbeats and release. A task left running without a heartbeat loses its claim. CLI network permissions must allow the configured coordinator.

For a human or an agent using the CLI directly, run these commands in the repository, with URL and token already set:

```sh
client=plugins/team-activity/skills/coordinate/activity.py
export TEAM_ACTIVITY_SESSION_FILE="$(mktemp -d)/lease"
python3 "$client" init
python3 "$client" claim --member Thant --agent API --branch thant/startup --task "Decouple demo startup" api/main.py
python3 "$client" heartbeat
python3 "$client" list
python3 "$client" release
```

Each parallel agent needs its own session file. Run `python3 "$client" watch` in a second terminal for changed snapshots every two seconds. Watching needs only the URL and team credential. A conflict exits with status 1 and prints the conflicting claim. After expiry, use `claim` again and check its result before editing. `release` is safe to repeat.

The plugin sees the tasks participants claim. Human-readable names are self-reported within the trusted team. The listing omits session credentials. This coordinates intent across worktrees and branches; Git and filesystem access operate independently. Use repository-relative canonical spelling for every path, including on case-insensitive clients. Keep summaries free of secrets, customer data, and private chat content.
