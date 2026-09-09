# Useful GitHub Repositories (as of 2026-06-01)

## Smart glasses and wearable implementations

| Repo | What it gives you | Why useful here |
|---|---|---|
| https://github.com/BasedHardware/OpenGlass | DIY AI-smart-glasses stack (hardware + firmware orientation) | Good reference for end-to-end wearable integration decisions |
| https://github.com/Mentra-Community/MentraOS | Smart-glasses OS + app/runtime ecosystem | Useful for studying production-ish wearable app architecture |
| https://github.com/Mentra-Community/OpenSourceSmartGlasses | Hardware + maker-focused smart glasses baseline | Helpful for hardware constraints and extension ideas |
| https://github.com/livekit/agents | Realtime voice/video agent framework | Strong patterns for low-latency voice-first interactions |

## Agent orchestration and multimodal systems

| Repo | What it gives you | Why useful here |
|---|---|---|
| https://github.com/openai/openai-agents-python | Lightweight multi-agent orchestration | Good baseline for tool-use + memory hooks |
| https://github.com/langchain-ai/langgraph | Stateful agent graphs | Useful for durable task continuity and resumable workflows |
| https://github.com/microsoft/autogen | Multi-agent collaboration framework | Reference for planner/executor role separation |
| https://github.com/deepset-ai/haystack | Pipeline and retrieval orchestration | Strong retrieval + memory design examples |
| https://github.com/crewAIInc/crewAI | Role-based autonomous agent teams | Useful for decomposing complex multi-step tasks |

## Product interface and deployment references

| Repo | What it gives you | Why useful here |
|---|---|---|
| https://github.com/open-webui/open-webui | Production-ready AI UX shell | Good ideas for controls, logs, and observability for agent outputs |

## Quick selection guidance
- If you need **realtime voice reliability** first: start with `livekit/agents`.
- If you need **stateful task continuity** first: start with `langgraph` + project-local memory manager.
- If you need **wearable hardware/software integration** first: compare `OpenGlass` and `MentraOS`.
