# Delegation-based Model Tiering (cheap default, strong on demand)

Cost-tiered routing without a separate bot: keep the main session on a cheap model
for chat/simple research; make heavy work (deep coding, problem solving) run on a
strong model by delegating it to a subagent.

## Config (per-profile)

```yaml
delegation:
  base_url: http://192.168.1.1:20128/v1   # same endpoint the parent uses
  model: OAO/claude-opus-5                  # strong model id from this endpoint's list
```

Apply with CLI, never hand-editing yaml:

```bash
hermes config set delegation.base_url "http://192.168.1.1:20128/v1"
hermes config set delegation.model "<strong-model-id>"
```

## How it resolves (read from tools/delegate_tool_config.py)

- **base_url branch**: `api_key` None → inherits the parent's key for that endpoint.
  No key env var needed when reusing the parent's route.
- **api_mode** auto-detected from the URL (`chat_completions` for /v1 OpenAI-shaped
  endpoints).
- **Pinned model** (provider/endpoint/model override set) ⇒ child does NOT borrow the
  parent's fallback chain — it won't silently drop back to a cheap fallback model.
- Provider-presence: a named provider like `custom:9router` resolves to its base_url;
  using `delegation.base_url` directly avoids provider-resolution surprises.

## Triggering

- Delegation fires on the agent's own judgment. To bias it, set a standing rule in
  the session: "Delegate substantial coding and deep problem-solving to subagents."
- Direct command for certainty: "Delegate this to a subagent."
- `/model` switches the *current session's* model — it does NOT affect delegation.

## Verification

Fire a tiny probe delegation and confirm it returns on the strong model:

```bash
# a probe goal like "reply exactly PROBE_OK, no tools" returns a token;
# check the result header shows the pinned model (e.g. OAO/claude-opus-5) and api_calls=1
```

## Pitfall — per-profile config targeting

`hermes config set` writes to the **active** profile. To edit a *different* profile's
config you must point HERMES_HOME at it:

```bash
HERMES_HOME=/opt/data hermes config set delegation.model "<id>"
```

- This host runs profiles under `/opt/data/profiles/<name>`, but the **default**
  profile (e.g. Dev/@devhamidrobot) is NOT under `profiles/` — its config is at
  `/opt/data/config.yaml` and requires `HERMES_HOME=/opt/data`.
- Verify after writing by grepping the target config for the `delegation:` block; a
  `config.yaml` that is empty/missing at `profiles/<name>/` usually means that profile
  is the default-profile-at-root, not a named profile.
- Delegation is per-profile: setting it for Shifu does nothing for Dev; each profile
  needs its own block, and only makes sense when that profile's main model is cheap.
