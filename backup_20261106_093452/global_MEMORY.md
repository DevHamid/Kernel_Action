Active: Home Assistant control; cron price watches every 12h (all deliver to group -1003628710660 thread 10669, not DM): iPhone minus <3.5M (excl bypass/wifi-only/iCloud-lock/simlock), Xiaomi 15T minus <4M, POCO X5 5G minus <1M, Redmi Note 11 Pro 5G minus <1M, Moto G45 minus <1M.
§
9Router: http://192.168.1.1:20128/v1 (API key needed remotely). STT at /v1/audio/transcriptions; Gemini Live/Transcribe need enabling as provider in dashboard first.
§
Telegram group -1003628710660; topic 9=Cooldown Room; General=no thread_id. Channel dir /opt/data/channel_directory.json. Gateways auto-discover new subtopics; no manual setup.
§
User convention: 'forward this' in DM → forward replied-to msg to group General subtopic. Wayne/OpenWrt dev talk lives in group -1003628710660 thread 441, not DM.
§
Dev (@devhamidrobot) + Shifu (@shifuisrobot) separate bots, require_mention:true, no profile switching; Dev delegates deep tasks to Shifu model.
§
Gateways need standalone:true + telegram; s6 DOWN unless gateway_state.json running; revive `hermes -p shifu gateway run --replace`; logs /opt/data/logs/gateways/<profile>/current. Shifu 9Router: chat_completions + ollama_num_ctx=0 (no 400), reasoning high.
§
Storage: box is x86_64 instabox, single 20G disk /dev/vdb mounted at /opt/data and /srv/ssd (same fs); host /data == container /srv/ssd, host /data/stacks/hermes == /opt/data. 4G swapfile.
§
Compression-wall: when auto-compression warning repeats, checkpoint BEFORE restarting (git commit/push or STATUS.md), update memory/skills, then /new. Repo/disk = source of truth; chat = scratch RAM.
§
A7 (t_e1e4f16c): POC+REFLEX backport on mglru-v5 complete, compile-check green. kanban_complete blocked by parent B6 (t_46bed900) status reset to todo during chain-realign; feed operator to restore parents.
§
Standing convention: always apply antislop rules to any generated code/UI/copy.
§
Fixed Moto G45 5G Minus Price Watch Indonesia cron job (024f528a9b57) by setting provider to 'custom' in /opt/data/cron/jobs.json. The job was blocked because base_url override required an explicit provider. After setting provider='custom', the job ran successfully with completed status.