# Free Provider Security Notes

Never paste API keys into source files, chat, issue trackers, workflow JSON,
or project artifacts. Keys pasted during the provider research discussion must
be revoked/rotated by the account owner.

## Provider Decisions

- Hugging Face Inference Providers: registered as experimental T2I/I2I. Uses
  `HF_TOKEN` from the environment. Free quota is limited and provider/model
  availability can change.
- Pollinations: not registered until its current authentication, quota, and
  data-retention terms are verified against its official API documentation.
- Puter.js: browser/user-pays model. Not a backend pipeline provider; using it
  would require user authentication and changes the privacy/cost model.
- Replicate/fal.ai: paid usage/trials, not classified as permanently free.
- Hosted I2V/TTS: no guaranteed free backend provider is currently enabled.

## Secret Handling

- Store keys only in environment variables or `.agent-secrets/`.
- Never commit `.env`, `.agent-secrets`, workflow exports containing headers, or
  n8n credentials.
- When a key is exposed, revoke it before continuing development.
