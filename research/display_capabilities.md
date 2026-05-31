# Meta Ray-Ban Display Capability Research

## Research Status

Active

Last Updated:
2026-05-31

---

## Hardware Verification

Status:
Confirmed

Evidence:

Meta View Device Information:

* Name: Display 00CX
* Model: Display
* Release Version: 125.0.0.190.412
* Lens Color: Grey Transitions

Conclusion:

The current project hardware is Meta Ray-Ban Display.

This project should no longer reference the earlier Wayfarer hardware assumptions.

---

## Display Overview

The display is currently the most important component of the project.

Research Goal:

Determine whether custom AI workflows can surface information directly through the Meta Ray-Ban Display experience.

---

## Confirmed Display Functions

### Weather Display

Status:
Confirmed

Test:

Asked Meta for the weather.

Result:

* Weather information appeared on the display.
* Meta also spoke the weather response.

---

### Time Display

Status:
Confirmed

Test:

Asked Meta what time it was.

Result:

* Meta spoke the time.
* The display showed the current time.

---

### Vision-Based Scene Understanding

Status:
Confirmed

Test:

Asked Meta what I was looking at.

Result:

* Meta analyzed the room.
* Meta described the room.
* AI response appeared through the glasses experience.

Engineering Significance:

Confirms a working:

Camera
↓
AI
↓
Display

pipeline exists on the device.

---

### Scrollable Display Content

Status:
Confirmed

Test:

Used the touch controls on the glasses arm.

Result:

* Display content can be scrolled.
* Longer responses can be navigated by the user.

---

### AI Response Display

Status:
Confirmed

Result:

* AI responses appear visually on the display.
* The display is not limited to icons.
* The display is not limited to notifications.
* The display can present generated AI content.

---

## Personally Verified Features

* Photo capture
* Video capture
* Audio capture
* Spotify playback
* Weather display
* Time display
* Vision analysis
* AI response display
* Scrollable display content
* Meta View synchronization
* iPhone connectivity

---

## Major Engineering Insight

The Meta Ray-Ban Display already supports:

Camera
↓
Meta AI
↓
Display Response

This means the hardware is capable of presenting AI-generated content.

The remaining engineering question is:

Can custom third-party software send custom AI responses into the display experience?

---

## Remaining Research Questions

### Third-Party Display Access

Question:

Can custom applications send information directly to the display?

Status:
Unknown

Priority:
Critical

---

### Notification Integration

Question:

Can iPhone notifications appear on the display?

Status:
Unknown

Priority:
High

---

### App Integration

Question:

Can custom applications trigger display content indirectly through notifications, Shortcuts, or supported app integrations?

Status:
Unknown

Priority:
Critical

---

### SDK Availability

Question:

Does Meta provide an SDK or developer interface for display interactions?

Status:
Unknown

Priority:
Critical

---

### External AI Integration

Question:

Can OpenAI or a custom Python backend return information in a way that appears on the Meta Ray-Ban Display?

Status:
Unknown

Priority:
Critical

---

## Possible Future Workflows

### Workflow A: Phone-Based Response

Meta Ray-Ban Display
↓
Capture Image
↓
Meta View / iPhone
↓
Custom AI Pipeline
↓
Phone Response

Complexity:
Low

Likelihood:
High

---

### Workflow B: Notification-Based Display Response

Meta Ray-Ban Display
↓
Capture Image
↓
Custom AI Pipeline
↓
iPhone Notification
↓
Display Notification

Complexity:
Medium

Likelihood:
Unknown

---

### Workflow C: Direct Display Response

Meta Ray-Ban Display
↓
Capture Image
↓
Custom AI Pipeline
↓
Direct Display Feedback

Complexity:
High

Likelihood:
Unknown

---

## Display Testing Queue

1. Test whether iPhone notifications appear on the display.
2. Test whether long Meta AI responses can be scrolled.
3. Test whether messages from apps appear on the display.
4. Test whether Shortcuts notifications appear on the display.
5. Research official Meta developer access.
6. Research third-party app integration limitations.
7. Research whether display content can be controlled through supported notification workflows.

---

## Engineering Impact

If display access is restricted:

Expected Architecture:

Glasses
↓
iPhone
↓
Custom AI
↓
Phone Response

---

If notification-based display access works:

Expected Architecture:

Glasses
↓
iPhone
↓
Custom AI
↓
iPhone Notification
↓
Display Notification

---

If direct display access is available:

Expected Architecture:

Glasses
↓
Custom AI
↓
Display Feedback
↓
User

---

## Current Assessment

The display has been verified as a functional AI response surface.

This is a major upgrade from the original project assumptions.

The highest-priority unknown is no longer whether the display can show AI responses.

The highest-priority unknown is whether custom software can route responses into the display through:

* Official APIs
* iPhone notifications
* Meta View integrations
* Shortcuts
* Supported companion app workflows
* Future SDKs

This question will heavily influence the final architecture of the wearable AI assistant.
