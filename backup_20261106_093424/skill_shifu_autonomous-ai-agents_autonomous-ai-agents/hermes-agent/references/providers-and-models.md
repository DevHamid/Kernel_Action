# Providers & Model Aliases

Set via `hermes model` (picker) or `hermes setup`. 35+ provider profiles ship as
plugins under `plugins/model-providers/`; user plugins of the same name override.
Full docs: https://hermes-agent.nousresearch.com/docs/integrations/providers

### Providers

| Provider | Auth | Key env var(s) |
|----------|------|----------------|
| openrouter | API key | `OPENROUTER_API_KEY` |
| anthropic | API key | `ANTHROPIC_API_KEY` (also `CLAUDE_CODE_OAUTH_TOKEN`) |
| nous | OAuth device code | `hermes auth add nous` (or `NOUS_API_KEY`) |
| openai-codex | OAuth | `hermes auth add openai-codex` |
| qwen-oauth | OAuth | `hermes auth add qwen-oauth` |
| minimax-oauth | OAuth | `hermes auth add minimax-oauth` |
| copilot | Token | `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` (Copilot device flow — `gh auth login` tokens do NOT work) |
| copilot-acp | External CLI | Copilot CLI on PATH or `COPILOT_CLI_PATH` |
| gemini | API key | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| xai | API key | `XAI_API_KEY` (SuperGrok OAuth also supported) |
| deepseek | API key | `DEEPSEEK_API_KEY` |
| zai (GLM) | API key | `GLM_API_KEY` / `ZAI_API_KEY` |
| minimax / minimax-cn | API key | `MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY` |
| kimi-coding / -cn | API key | `KIMI_API_KEY` / `KIMI_CN_API_KEY` |
| alibaba (+coding-plan) | API key | `DASHSCOPE_API_KEY` / `ALIBABA_CODING_PLAN_API_KEY` |
| xiaomi | API key | `XIAOMI_API_KEY` |
| huggingface | Token | `HF_TOKEN` |
| fireworks / novita / nvidia / deepinfra / gmi / arcee / stepfun / upstage / kilocode / ai-gateway / opencode-zen / opencode-go / ollama-cloud | API key | `<NAME>_API_KEY` |
| bedrock / vertex / azure-foundry | Cloud SDK / key | AWS SDK creds / Vertex ADC / `AZURE_FOUNDRY_API_KEY` |
| custom | Config | `model.base_url` + `model.api_key` in config.yaml |

Multiple credentials per provider pool and rotate automatically (`hermes auth`).
Fallback chain when the primary fails: `hermes fallback add|remove|list`.

### User-defined model aliases

Work with `/model <name>` in CLI and every gateway platform. Resolved by
`hermes_cli/model_switch.py::resolve_alias()`; user aliases are checked BEFORE
the built-in table, so a user `sonnet`/`grok` shadows the built-in.

```yaml
# Full form
model_aliases:
  fav:
    model: claude-sonnet-4.6
    provider: anthropic
  local-qwen:
    model: qwen3.5:397b
    provider: custom
    base_url: "https://ollama.com/v1"
  theta:
    model: theta-1
    provider: custom
    base_url: "https://theta.example.com/v1"
    key_env: THETA_API_KEY        # or: api_key: "${THETA_API_KEY}"

# Short form ("provider/model"), also via CLI:
#   hermes config set model.aliases.fav openrouter/anthropic/claude-sonnet-4.6
model:
  aliases:
    fav: openrouter/anthropic/claude-sonnet-4.6
```

`/model fav` — session-scoped; add `--global` to persist as default.

An alias with its own `base_url` authenticates with its own credential
(`api_key`, which also accepts a `"${VAR}"` reference, or `key_env`). With
neither set the key is resolved from the alias HOST, never carried over from
the provider that was active before the switch.

Built-in aliases (catalog-resolved against the active provider): `sonnet`,
`opus`, `haiku`, `claude`, `gpt5`, `gpt`, `codex`, `o3`, `o4`, `gemini`,
`deepseek`, `grok`, `llama`, `qwen`, `minimax`, `nemotron`, `kimi`, `glm`,
`step`, `mimo`, `trinity`.

## Switching the default model and the fallback chain

On a profile install, export the profile home first (`export HERMES_HOME=/path/to/profile`);
without it the CLI edits the wrong home and the change never reaches the running bot.

```bash
hermes config set model.default '<provider>/<model>'
hermes config get model.default          # always re-read — never assume the set landed
```

The fallback chain is the `fallback_providers` config key: a JSON array of
`{provider, model, base_url}` objects, tried in order. Set the whole array at once —
the config path has no per-entry append:

```bash
hermes config set fallback_providers '[{"provider":"custom","model":"a","base_url":"https://host/v1"},{"provider":"custom","model":"b","base_url":"https://host/v1"}]'
hermes config get fallback_providers
```

Procedure, in order:

1. **Back up the profile config first** — `cp config.yaml <scratch>/config.yaml.bak.$(date +%s)`.
   A bad `config set` against a live gateway config is the one edit that can break
   every session on that profile.
2. **Confirm the exact model id** with `curl -s $BASE_URL/v1/models -H "Authorization: Bearer $KEY"`
   and grep the id. Ids are exact strings: `OAO/claude-opus-5` and
   `OAO/claude-opus-5.5` are different models, and a near-miss id is accepted by
   `config set` and only fails at request time.
3. **Smoke-test the model before making it default** — one tiny completion
   (`max_tokens` 16-32, "reply with one word: ok") proves the route, the key, and
   the id in one call. The response echoes the served model id, which is the ground
   truth when the requested id was aliased.
4. **Set the default, then set the fallback array**, then re-read both keys.
5. **Report the exact id you set** back to the user, verbatim, so a mis-typed
   generation number is caught in the same turn.

Rules that keep the chain sane:

- The default model must not also appear in `fallback_providers` — a fallback equal
  to the primary can never fire and hides the real second option.
- Keep `base_url` on every entry. An entry without one resolves against the default
  route and silently fails over to the wrong endpoint.
- Config-only changes need **no gateway restart**: the gateway re-reads config at
  session create. Reserve `s6-svc -r /run/service/gateway-<name>` for plugin
  changes, and make it the last action of a task because it kills the live session.
- A running session keeps the window and model it started with; the new default
  applies to the next session.

Pitfall: `hermes config set` with a bracketed path (`custom_providers[0].model`)
can leave a stray duplicate entry in the file. After any bracketed write, grep for
top-level bracketed keys (`grep -n '^[a-z_]*\[' config.yaml`), `hermes config unset`
whatever is stray, then re-parse the YAML to confirm the provider list is back to
its original entries.

## Context-window resolution

`model.context_length` is a hard pin that overrides every other source. To let the
window follow the model itself, remove the pin — do not set it to 0:

```bash
hermes config unset model.context_length
```

Resolution order once the pin is gone (`agent/model_metadata.py::get_model_context_length`):
`model_overrides` / `custom_providers` per-model entries → the endpoint-scoped cache
(`<profile>/context_length_cache.yaml`) → the endpoint's own `/models` probe
(`context_length` and `capabilities.contextWindow` per id) → provider catalog →
256K fallback. The status output's `context_source` names which one won
(`config`, `detected`, or `default`).

Check what Hermes will resolve without starting a session, using the Hermes venv
interpreter (the system python lacks Hermes' dependencies and fails on import):

```bash
/opt/hermes/.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, '/opt/hermes')
from agent.model_metadata import get_model_context_length
print(get_model_context_length('vendor/model-id', base_url='https://host/v1', api_key=KEY, provider='custom'))
EOF
```

`ollama_num_ctx: 0` means "no override" and only applies to Ollama routes — leave
it alone. The endpoint cache is self-managed; only clear entries for models the
user actually runs.
