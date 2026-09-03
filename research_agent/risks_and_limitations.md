# Risks and Limitations

## 1) Hardware limitations
- **Battery**: continuous camera + audio + network quickly drains power.
- **Thermals**: sustained on-device inference can throttle performance.
- **Sensor limits**: blur, low light, narrow FOV, and occlusion degrade vision accuracy.
- **I/O constraints**: small display + audio-only outputs limit information density.

## 2) Platform and integration risks
- Limited or changing third-party integration points for commercial glasses platforms.
- Vendor ecosystem dependencies can break workflows after firmware/app updates.
- BLE/Wi-Fi handoff instability can cause intermittent real-time failures.

## 3) Model and agent risks
- Hallucinations in ambiguous visual scenes.
- Overconfident task recommendations from low-quality inputs.
- Memory contamination (stale or incorrect task state influencing future steps).
- Latency spikes that break conversational turn-taking.

## 4) Privacy, safety, and compliance risks
- Capturing bystanders, screens, or sensitive documents unintentionally.
- Storing persistent personal context without clear retention boundaries.
- Unsafe autonomous actions without confirmation loops.

## 5) Product/UX risks
- Voice interface fatigue if responses are too long or repetitive.
- User trust erosion if assistant frequently asks for retries.
- Cognitive overload if output channel selection (voice/display/phone) is inconsistent.

## 6) Mitigations to prioritize
- Confidence-gated behavior with explicit fallback prompts.
- Clear retention policy for memory records (TTL + deletion controls).
- Policy layer before tool actions.
- Structured observability (latency/error/fallback metrics) for rapid iteration.
