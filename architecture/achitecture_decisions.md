# System Architecture

## Project Hardware

Meta Ray-Ban Display

Verified Device Information:

* Name: Display 00CX
* Model: Display
* Release Version: 125.0.0.190.412

---

## Current System Understanding

The Meta Ray-Ban Display supports:

* Photo capture
* Video capture
* Audio capture
* Audio playback
* Meta AI interaction
* Vision-based scene understanding
* Visual AI responses on the display
* Scrollable display content
* iPhone and Meta View synchronization

---

## Confirmed Native Workflow

Meta Ray-Ban Display
↓
Camera Capture
↓
Meta AI
↓
Display Response
↓
User

This workflow has been personally verified by asking Meta what the user was looking at.

---

## Current Custom AI Architecture

This is the most realistic initial architecture for Prototype V1:

Meta Ray-Ban Display
↓
Meta View / iPhone
↓
Image Access
↓
Custom Python Application
↓
OpenAI Vision Model
↓
Response

---

## Component Responsibilities

### Meta Ray-Ban Display

Responsibilities:

* Capture photos
* Capture video
* Capture audio
* Run supported Meta AI interactions
* Show native display responses
* Provide wearable user interface

---

### Meta View App

Responsibilities:

* Manage device pairing
* Sync captured media
* Configure glasses
* Provide access to device information
* Bridge glasses and iPhone ecosystem

---

### iPhone

Responsibilities:

* Store captured media
* Provide access to photos/videos
* Potentially trigger Shortcuts workflows
* Potentially deliver notifications to the display

---

### Custom Python Application

Responsibilities:

* Accept image input
* Send images to OpenAI models
* Return structured AI analysis
* Support OCR workflows
* Support coding-assistant workflows
* Log requests and responses
* Serve as the backend for future integrations

---

### OpenAI Models

Responsibilities:

* Image analysis
* OCR-style text extraction
* Scene understanding
* Coding screenshot analysis
* Response generation

---

## Architecture Pathways

### Pathway A: Phone-Based Response

Meta Ray-Ban Display
↓
iPhone
↓
Custom Python AI
↓
Phone Response

Likelihood:
High

Description:

This path assumes custom AI output is shown on the phone, not directly in the glasses display.

---

### Pathway B: Notification-Based Display Response

Meta Ray-Ban Display
↓
iPhone
↓
Custom Python AI
↓
iPhone Notification
↓
Display Notification

Likelihood:
Unknown

Description:

This path depends on whether iPhone notifications from custom workflows appear on the Meta Ray-Ban Display.

---

### Pathway C: Direct Display Response

Meta Ray-Ban Display
↓
Custom AI Backend
↓
Display Response

Likelihood:
Unknown

Description:

This path depends on whether Meta exposes direct developer access to the display or supports third-party display integrations.

---

## Prototype V1 Architecture

Goal:

Validate a basic custom AI image-analysis workflow.

Image File
↓
Python Script
↓
OpenAI Vision Model
↓
Printed Response

Inputs:

* Local image file
* User question

Outputs:

* AI-generated description
* OCR-style extracted text when available
* Structured analysis

---

## Prototype V2 Architecture

Goal:

Support coding and OCR workflows.

Image or Screenshot
↓
Python Script
↓
Vision Analysis
↓
OCR / Text Extraction
↓
Technical Explanation
↓
Saved Log

---

## Prototype V3 Architecture

Goal:

Test wearable-oriented response delivery.

Meta Ray-Ban Display
↓
iPhone / Shortcut / Notification
↓
Custom AI Pipeline
↓
User-Facing Response

---

## Highest-Priority Unknowns

1. Can custom software send responses to the Meta Ray-Ban Display?
2. Do iPhone notifications appear on the display?
3. Can iOS Shortcuts participate in the workflow?
4. Can Meta View media be accessed automatically?
5. Does Meta provide an SDK for display interaction?
6. Can captured images be routed to a backend with minimal friction?

---

## Current Engineering Strategy

Do not assume direct display control.

Build the first prototype around a reliable image-analysis pipeline.

Research display integration in parallel.

This prevents the project from being blocked by unknown platform restrictions while still keeping the display-centered architecture as the long-term goal.
