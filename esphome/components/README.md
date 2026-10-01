# Shared ESPHome components

ESPHome external components used by more than one aikos device (door station and room keys), so the devices can't drift apart.
They are maintained jointly by the intercom and roomkey maintainers.

- Each component has its own versioned tags (e.g. `voice-v1.0.0`); devices pin a tag, never a branch.
- A component's regression test must pass before a tag is set.
- Changes go through a pull request reviewed by both device maintainers.

The interface each component implements is documented next to its code.

| Component | Job | Tag |
|---|---|---|
| [`aikos_voice`](aikos_voice/README.md) | Voice link door ⇄ room keys (RTP push-to-talk, transcriber copy, door lock) | `voice-v1.0.0` |
