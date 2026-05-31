# Meta Ray-Ban Display Capability Research

## Research Status

Active

Last Updated:
2026-05-31

---

## Hardware Platform

Current Hardware:
Meta Ray-Ban Display

Verified Device Information:

* Name: Display 00CX
* Model: Display
* Release Version: 125.0.0.190.412
* Lens Color: Grey Transitions

Previous Hardware Assumption:
Meta Ray-Ban Wayfarer

Status:
Replaced

---

## Confirmed Core Capabilities

### Photo Capture

Status:
Confirmed

Evidence:

Successfully captured photos using the glasses and viewed them through Meta View on iPhone.

---

### Video Capture

Status:
Confirmed

Evidence:

Successfully recorded video using the glasses and verified media transfer through Meta View.

---

### Audio Capture

Status:
Confirmed

Evidence:

Successfully used audio functionality and verified microphone operation.

---

### Audio Playback

Status:
Confirmed

Evidence:

Successfully connected the glasses to Spotify and played audio through the glasses speakers.

---

### Meta AI Voice Assistant

Status:
Confirmed

Evidence:

Meta AI responds to voice commands.

Verified Commands:

* Weather query
* Time query
* Vision query asking what the user was looking at

---

### Display-Based AI Responses

Status:
Confirmed

Evidence:

AI responses appeared visually on the Meta Ray-Ban Display.

---

### Scrollable Display Content

Status:
Confirmed

Evidence:

Display content can be scrolled using the glasses controls.

---

## Verified Native AI Workflows

### Weather

Command:

Asked Meta for the weather.

Result:

* Weather appeared on the display.
* Weather response was spoken aloud.

---

### Time

Command:

Asked Meta what time it was.

Result:

* Time response was spoken aloud.
* Time appeared on the display.

---

### Scene Understanding

Command:

Asked Meta what the user was looking at.

Result:

* Meta analyzed the room.
* Meta described the room.
* AI response appeared through the glasses experience.

Engineering Significance:

Confirms a native:

Camera
↓
AI
↓
Display

workflow exists on the hardware.

---

## Media Workflow

Current Understanding:

Meta Ray-Ban Display
↓
Meta View App
↓
iPhone

Confirmed:

* Photos reach Meta View.
* Videos reach Meta View.
* Media is accessible through the iPhone ecosystem.
* Device information is visible inside Meta View.

Unknown:

* Automatic export options
* API access options
* iOS Shortcuts integration
* Notification-to-display behavior
* Real-time media access
* Third-party display access

---

## Potential AI Features

### Vision Analysis

Priority:
High

Use Cases:

* Scene understanding
* Object identification
* Environment analysis
* Context-aware assistance

---

### OCR

Priority:
High

Use Cases:

* Read signs
* Read computer screens
* Read documents
* Extract text from images

---

### Coding Assistant

Priority:
High

Use Cases:

* Analyze code screenshots
* Explain errors
* Assist debugging
* Review architecture diagrams

---

### Technical Documentation Assistant

Priority:
Medium

Use Cases:

* Read documentation
* Summarize content
* Explain concepts
* Answer technical questions

---

## Current Limitations

### Direct Display API Access

Status:
Unknown

Research Required

---

### Third-Party App Display Integration

Status:
Unknown

Research Required

---

### Real-Time Streaming

Status:
Unknown

Research Required

---

### Automated Media Transfer

Status:
Unknown

Research Required

---

## Testing Queue

1. Test whether iPhone notifications appear on the display.
2. Test whether Shortcuts notifications appear on the display.
3. Test whether app messages appear on the display.
4. Test long AI responses and scrolling limits.
5. Test image transfer workflow from Meta View to iPhone Photos.
6. Validate GPT Vision integration with a captured image.
7. Research official SDK or developer access.
8. Investigate real-time workflow limitations.

---

## Key Project Goal

Build a workflow that allows media captured by Meta Ray-Ban Display glasses to be processed by custom AI tools.

Long-term objective:

Capture
↓
Analyze
↓
Understand
↓
Respond

Potential final objective:

Capture
↓
Custom AI
↓
Display Response
