# Free Cloud Provider Matrix

Research basis: official Hugging Face Inference Providers, Hugging Face Spaces,
Replicate billing, and fal.ai API documentation reviewed 2026-09-10.

## T2I / I2I

**Candidate:** Hugging Face Inference Providers

- Free Hugging Face token/account path exists.
- Official provider table supports text-to-image.
- Image generation is available through the official Python client and router.
- Quota and provider availability are limited and can change.
- This is registered as an experimental opt-in provider, not the local default.

Environment variable:

```text
HF_TOKEN
```

## I2V

Hugging Face lists video-capable inference partners, but there is no permanent,
provider-independent free I2V quota that can be promised. The registry contains
an unavailable extension slot so a verified adapter can be added later without
redesigning the UI.

The default remains local LTX2B.

## TTS

No reliable permanently free hosted TTS API was identified for this stack. The
local chain remains:

```text
Kokoro -> espeak-ng
```

A disabled generic hosted TTS slot is registered for a future explicitly chosen
provider. It is not enabled and does not send audio/text anywhere.

## Not Labeled Free

Replicate and fal.ai provide API access but are pay-as-you-go services. Some
models or accounts may have trials/free credits, but they are not safe defaults
for a “free API key” promise. They should be added only with explicit billing
approval and spend limits.
