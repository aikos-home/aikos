# The AI host

The machine that runs aikos' local models: speech to text, the transcriber, the voice (TTS) and the language model.
Today an Apple Silicon Mac; tomorrow perhaps a Linux machine with an NVIDIA GPU. This page is how every aikos service on
it is laid out, so that the services don't get in each other's way and the whole set can move to new hardware by copying
one folder and deploying tags. House values (addresses, names, which machine) are not in this repository.

## The services

| Service | Block | Job | Unit (macOS LaunchAgent) |
|---|---|---|---|
| Speech to text, live | whisper.cpp `whisper-server` | transcribes calls as they happen; nothing else uses it | an older LaunchAgent (historic label) |
| Speech to text, shared | whisper.cpp `whisper-server` | everything else: long audio, checks, other projects | `home.aikos.whisper-shared` |
| Language model | Ollama | "who is speaking" and later the house assistant | `com.ollama.ollama` |
| AI broker | aikos hub (own project) | decides which client may use which model when; routes; admission control | `home.aikos.hub` |
| Transcriber | [`services/transcriber`](../services/transcriber/) | turns call audio into the chat in Home Assistant | `home.aikos.transcriber.room`, `.door` |
| Heartbeat | `services/transcriber` (`heartbeat.py`) | pushes the transcriber's health to the monitor | `home.aikos.heartbeat` |
| Voice | [`services/tts`](../services/tts/) | speaks residents' notes in their own voice | `home.aikos.tts` |

Labels are `home.aikos.<service>`; one unit per job (CLAUDE.md: one building block, one job).

## Ports

| Port | Who | Bound to | Clients |
|---|---|---|---|
| TCP 80 | aikos hub | all | anything that wants a model (`/c/<client>/…`), health checks |
| TCP 6667 | whisper, live | all | the transcriber only (reserved for aikos live speech) |
| TCP 6668 | whisper, shared | localhost | through the hub only |
| TCP 11434 | Ollama | all | through the hub; one direct health check on purpose (tells "hub dead" from "Ollama dead") |
| TCP 10200 | voice, Wyoming | all, allow list | the Home Assistant hosts |
| TCP 10201 | voice, HTTP | all, allow list + token | the aikos app nodes |
| UDP 5006 / 5008 | transcriber | all | room keys / door (call audio) |

A new service takes a free port, adds a row here and to the house register, and says so in the change.

## Rules

1. **Live speech comes first.** A call's transcription has its own whisper instance and must never wait behind
   background work. Background work (a voice check, preparing notes, long recordings) goes to the shared instance through
   the hub, as its own hub client. The GPU is shared: a service that keeps a model loaded tells the hub (as a backend it
   checks), so admission control knows it.
2. **Code from a tag.** Each service is deployed with its own `deploy.sh <tag>`: tests on the host first, then the units,
   a smoke test against test entities or the model's built-in voice only (never a resident's), and an automatic rollback
   to the previous version if any step fails. Never edit code on the host. A service runs from its own release folder
   (`~/aikos/releases/<service>/<tag>/`, exported from the tag, with its own environment); a deploy never checks out a tag
   in a tree another service runs from. (The transcriber still runs from the clone `~/aikos/repo`; nothing else may move
   that clone's working tree.)
3. **State in one folder.** Everything that cannot be rebuilt lives in `~/.aikos/` (mode 0700): settings files, tokens
   (0600) and personal data such as recorded voices (0700). Code, virtual environments, caches and model weights are
   rebuilt by the installer and are never copied or backed up.
4. **Pinned.** The interpreter (an absolute path, uv-managed), the dependencies (a lockfile per platform) and every model
   (a fixed revision). A service starts without the internet (`HF_HUB_OFFLINE=1`); a model never changes by itself on a
   restart.
5. **Logs** go to `~/Library/Logs/aikos/<service>.log` (Linux: the journal). They are rotated daily, and a log that can
   hold speech or text (transcripts, notes) keeps today and the day before only.
6. **Names, not addresses.** Clients reach the host by a name per role (the hub, the voice), never by an IP, so one role
   can move without the others. HTTP goes through the hub's name; protocols the hub cannot carry (Wyoming is plain TCP)
   get a name of their own.
7. **Health and heartbeat.** Each service answers a health request with its version (and engine or model where it has
   one). Each pushes its own heartbeat to its own push monitor every 30 s, window 120 s: up only when what it needs works,
   and the message names the cause. Problems of the host itself (for example the macOS TCP clock that wraps after 49.7 days
   of uptime) are reported once, by one check, not by every service.
8. **Backups.** Personal data only encrypted; model weights and caches never.

## Engines

| Hardware | Speech to text | Voice | Language model |
|---|---|---|---|
| Apple Silicon | whisper.cpp (Metal) | MLX | Ollama (Metal) |
| NVIDIA | whisper.cpp (CUDA) | PyTorch on CUDA, in a container with the GPU | Ollama (CUDA) |
| CPU only | emergency use; too slow for live calls | emergency use | emergency use |

A service picks its engine from the hardware (`auto`) or from its settings; its interface does not change. In a container,
a service that allows clients by source address needs host networking (behind NAT every client has the bridge's address).

## Moving to a new host

1. **Prepare the new host:** git, uv, ffmpeg; whisper.cpp and Ollama with the same models (Linux: the NVIDIA driver and
   the container toolkit). macOS: sign in once, so that LaunchAgents start.
2. **Deploy each service from its tag** with its `deploy.sh`; the installer builds the environments and fetches the pinned
   models. Copy `~/.aikos/` first (or import the voices from their encrypted export).
3. **macOS Local Network permission:** a LaunchAgent whose interpreter is not Apple's own may reach the LAN only once it
   is allowed in System Settings → Privacy & Security → Local Network. Check with a short LaunchAgent probe before
   switching anything (without the permission: `[Errno 65] No route to host`; loopback still works).
4. **Smoke test each service** (test entities and the synthetic test voice only).
5. **Switch the names one role at a time** and watch the heartbeats. The old host stays ready as the way back until every
   heartbeat has been green for a day.
6. **Then wipe the personal data** (`~/.aikos/`) on the old host.

A move is practised before it is needed: restore `~/.aikos/` into a scratch folder and start each service against it.
