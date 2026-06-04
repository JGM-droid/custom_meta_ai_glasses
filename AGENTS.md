# Project Memory

Project:
Custom Meta AI Glasses

Purpose:
Wearable AI workflow assistant for software development.

Current Architecture:
VS Code
-> Active Editor Signal
-> Active Editor Context
-> Context Fusion
-> Guidance Engine
-> resume_now.json
-> FastAPI
-> Glasses Display
-> Desktop Prompt Panel

Signals Available:
- Active file
- Language
- Dirty state
- Git state
- Terminal errors
- Coding session snapshot

Current Features:
- Active file awareness
- File-aware guidance
- Context fusion
- Desktop prompt panel
- Copy-to-AI workflow

Design Rules:
- Preserve guidance priority ordering
- Preserve context fusion architecture
- Fail gracefully when signals are missing
- Keep display layer separate from signal layer
- Prefer additive changes over rewrites

Current Milestone:
V8.1 Project Memory

Future Vision:
Generate context-aware prompts that can be pasted into:
- ChatGPT
- Copilot
- Claude
- Cursor
- Cline
