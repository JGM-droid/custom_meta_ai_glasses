# System Architecture

## Version 1 Architecture

Current architecture based on:

- Meta Ray-Ban Smart Glasses
- iPhone
- Meta View App
- OpenAI APIs
- Python Backend

---

## High-Level Workflow

Meta Ray-Ban Glasses
        ↓
Capture Photo
        ↓
Meta View App
        ↓
iPhone Photo Storage
        ↓
Custom Python Application
        ↓
OpenAI Vision Analysis
        ↓
Response Generation
        ↓
User

---

## Component Breakdown

### Meta Ray-Ban Glasses

Responsibilities:

- Capture photos
- Capture video
- Capture audio
- Trigger Meta AI interactions

---

### Meta View App

Responsibilities:

- Sync media from glasses
- Store captured media on iPhone
- Manage device settings

---

### iPhone

Responsibilities:

- Store captured media
- Act as bridge between glasses and AI pipeline

---

### Custom Python Application

Responsibilities:

- Receive images
- Process requests
- Send images to OpenAI APIs
- Handle OCR
- Manage AI workflows
- Log results

---

### OpenAI Services

Responsibilities:

- Image analysis
- OCR assistance
- Question answering
- Coding assistance

---

## Planned Future Features

### OCR Pipeline

Image
    ↓
OCR Engine
    ↓
Extracted Text
    ↓
GPT Analysis

---

### Coding Assistant Pipeline

Screenshot
    ↓
Vision Model
    ↓
Code Analysis
    ↓
Explanation
    ↓
User Response

---

## Current Constraints

1. No direct glasses-to-Python connection confirmed.
2. Media currently flows through Meta View.
3. Real-time streaming capability not yet validated.
4. Automation workflow still under investigation.

---

## Next Technical Goal

Determine how captured media can automatically enter the custom AI pipeline.