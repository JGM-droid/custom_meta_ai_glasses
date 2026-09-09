# Meta Wearables Web App Platform Validation

Last updated: 2026-06-01

## Executive Summary

- **Yes — Meta Ray-Ban Display can run custom web apps today.** Meta's public `facebookincubator/meta-wearables-webapp` toolkit states that Web Apps are standard HTML/CSS/JavaScript applications rendered on Meta Ray-Ban Display glasses. ([toolkit README](https://github.com/facebookincubator/meta-wearables-webapp))
- **Access looks like an early public platform, not a mature GA store.** The Web App toolkit is public, but Meta's official DAT SDK repos explicitly say the broader wearable developer platform is **in developer preview** and uses organizations/release channels/test users. ([Android DAT README](https://github.com/facebook/meta-wearables-dat-android), [iOS DAT README](https://github.com/facebook/meta-wearables-dat-ios))
- **FastAPI can absolutely be part of the architecture.** The glasses display is driven by a front-end web app, and that web app can call any HTTPS REST/WebSocket backend. Meta's toolkit even includes a `connect-api` capability, and community projects already use the same pattern with an API server. ([toolkit README](https://github.com/facebookincubator/meta-wearables-webapp), [Soma HUD](https://github.com/CarlKho-Minerva/soma-hud))
- **Custom AI responses can be rendered on the display, but only inside your own app UI.** You can render LLM output as text/cards in your web app. There is **no evidence** that third parties can replace or directly inject into Meta's built-in assistant UI.
- **Recommended direction for this repository:** validate with a **small Web App + FastAPI POC**, not the native DAT SDK path, because the web route is simpler, public-facing, and already matches the need to render glanceable AI output.

## Direct Answers

| Question | Answer | Evidence |
| --- | --- | --- |
| Can Meta Ray-Ban Display run custom web apps today? | **Yes.** | Meta's public Web App toolkit says Web Apps are rendered on Meta Ray-Ban Display glasses. ([toolkit README](https://github.com/facebookincubator/meta-wearables-webapp)) |
| Is access public, beta, or invite-only? | **Best classified as public preview / public beta.** Public repos and docs exist, but official DAT repos say the platform is in **developer preview**. | ([toolkit README](https://github.com/facebookincubator/meta-wearables-webapp), [Android DAT README](https://github.com/facebook/meta-wearables-dat-android), [iOS DAT README](https://github.com/facebook/meta-wearables-dat-ios)) |
| Are there Hello World / starter examples? | **Yes.** Official Snake example plus scaffold instructions exist. | ([examples/snake](https://github.com/facebookincubator/meta-wearables-webapp/tree/main/examples/snake), [toolkit README](https://github.com/facebookincubator/meta-wearables-webapp)) |
| What are the deployment requirements? | **Public HTTPS URL, 600x600 UI, D-pad-friendly interaction, high-contrast dark UI, then add the app in Meta AI app settings.** | ([toolkit README](https://github.com/facebookincubator/meta-wearables-webapp)) |
| Can FastAPI drive display content? | **Yes, indirectly.** FastAPI can provide JSON/WebSocket data to the web app; the web app renders it. | ([toolkit README](https://github.com/facebookincubator/meta-wearables-webapp), [Soma HUD](https://github.com/CarlKho-Minerva/soma-hud)) |
| Can custom AI responses be rendered on the display? | **Yes, inside your own app.** Use the web app to display AI output. | ([toolkit README](https://github.com/facebookincubator/meta-wearables-webapp), [Soma HUD](https://github.com/CarlKho-Minerva/soma-hud), [DisplayAccess sample iOS](https://github.com/facebook/meta-wearables-dat-ios/tree/main/samples/DisplayAccess)) |

## Official Meta Documentation

### Primary official resources

- Wearables Developer Center: <https://wearables.developer.meta.com/>
- Web Apps docs root: <https://wearables.developer.meta.com/docs/develop/webapps>
- General wearable developer docs: <https://wearables.developer.meta.com/docs/develop/>
- Android DAT API reference: <https://wearables.developer.meta.com/docs/reference/android/dat/0.7>
- iOS DAT API reference: <https://wearables.developer.meta.com/docs/reference/ios_swift/dat/0.7>
- LLM-friendly docs index: <https://wearables.developer.meta.com/llms.txt?full=true>

### Official public code

- Meta Wearables Web App toolkit: <https://github.com/facebookincubator/meta-wearables-webapp>
- Meta Wearables DAT for Android: <https://github.com/facebook/meta-wearables-dat-android>
- Meta Wearables DAT for iOS: <https://github.com/facebook/meta-wearables-dat-ios>

## Architecture Diagram

```text
┌──────────────────────────────┐
│  Meta Ray-Ban Display        │
│  600x600 Web App UI          │
│  - short text/cards          │
│  - D-pad / gesture focus     │
└──────────────┬───────────────┘
               │
               │ renders HTML/CSS/JS app
               ▼
┌──────────────────────────────┐
│  Front-End Web App           │
│  - index.html                │
│  - app.js                    │
│  - response screen           │
│  - fetch/WebSocket client    │
└──────────────┬───────────────┘
               │ HTTPS
               ▼
┌──────────────────────────────┐
│  FastAPI Backend             │
│  - /ask                      │
│  - /health                   │
│  - auth / rate limiting      │
│  - LLM provider integration  │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  OpenAI / Anthropic / Other  │
│  Retrieval / business logic  │
└──────────────────────────────┘
```

### Interpretation

- **The web app is the thing the glasses render.**
- **FastAPI is the backend, not the display runtime.**
- This means Python is viable for app logic and AI orchestration, but the on-glasses surface still needs HTML/CSS/JS.

## Setup Steps

## 1) Confirm the platform path

Choose the **Web App** path, not the DAT-native path, if your goal is:

- the fastest possible proof of feasibility
- a custom UI on Meta Ray-Ban Display
- a simple backend-driven AI experience

Use the **DAT SDK** only if you later need deeper device integration or native mobile-app flows. The official DAT repos are still labeled **developer preview**. ([Android DAT README](https://github.com/facebook/meta-wearables-dat-android), [iOS DAT README](https://github.com/facebook/meta-wearables-dat-ios))

## 2) Start from Meta's official Web App toolkit

- Review Meta's toolkit: <https://github.com/facebookincubator/meta-wearables-webapp>
- Study the official example app: <https://github.com/facebookincubator/meta-wearables-webapp/tree/main/examples/snake>
- Use Meta's documented design constraints:
  - **600x600 viewport**
  - **D-pad navigation**
  - **dark backgrounds**
  - **high contrast**
  - **`.focusable` class** for interactive elements

## 3) Build the web UI

Meta's public toolkit describes the expected flow:

1. Create a standard HTML/CSS/JS app.
2. Test it in a desktop browser.
3. Use arrow keys to simulate D-pad input.
4. Keep the UI glanceable and high-contrast.

For this repository's use case, the minimal UI should be:

- **Home screen**
- **Prompt / task screen**
- **Response screen** showing short AI output

## 4) Add the backend

Use FastAPI to provide:

- `POST /ask` for prompt submission
- `GET /health` for readiness
- optional `GET /session/:id` or WebSocket stream for live updates

The web app calls FastAPI over HTTPS and renders the result on the 600x600 UI.

## 5) Deploy

Meta's public toolkit is explicit:

- the app must be hosted at a **publicly available HTTPS URL**
- Vercel is supported by the toolkit, but any HTTPS host works
- once deployed, add the web app from the **Meta AI app**

Manual flow from Meta's toolkit:

1. Open the **Meta AI app** on your phone
2. Go to **Devices**
3. Open **Display Glasses settings**
4. Open **App connections**
5. Open **Web apps**
6. Tap **Add a web app**
7. Enter the app name and deployed URL

Source: [Meta Web App toolkit README](https://github.com/facebookincubator/meta-wearables-webapp)

## 6) Validate with a real task

Recommended validation flow:

1. Hardcode a few prompts first
2. Confirm response readability on the display
3. Add FastAPI integration
4. Measure whether responses stay understandable in 1-3 short cards
5. Only then add live or multimodal behavior

## Screenshots / Examples

## Official examples

| Source | What it shows | Link |
| --- | --- | --- |
| Meta Web App toolkit | Official public Web App entry point and platform constraints | <https://github.com/facebookincubator/meta-wearables-webapp> |
| Snake example | A complete 600x600 HTML/CSS/JS app with D-pad controls and focusable buttons | <https://github.com/facebookincubator/meta-wearables-webapp/tree/main/examples/snake> |
| iOS DisplayAccess sample | Official sample that sends display content to Meta Ray-Ban Display via DAT | <https://github.com/facebook/meta-wearables-dat-ios/tree/main/samples/DisplayAccess> |
| Android DisplayAccess sample | Same concept on Android | <https://github.com/facebook/meta-wearables-dat-android/tree/main/samples/DisplayAccess> |

## Community example worth studying

| Source | What it shows | Link |
| --- | --- | --- |
| Soma HUD | A working 600x600 MRBD HUD for AI output; useful proof that backend-driven AI responses can be rendered as a display-first surface | <https://github.com/CarlKho-Minerva/soma-hud> |

## Notes on screenshots

- In this sandbox, the official docs pages themselves were not directly fetchable, so this validation relies on **official public repos** plus linked examples.
- The strongest publicly verifiable artifacts are currently **code examples and sample apps**, not a large gallery of official in-lens screenshots.
- If visual capture is required for a follow-up phase, the best next step is a manual pass through the Meta developer center and current launch coverage once browser access to those pages is available.

## Hello World Example

Meta does not expose a tiny standalone "Hello World" sample in this repository, but the official toolkit is enough to derive one:

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=600, height=600, initial-scale=1.0, user-scalable=no" />
    <title>Hello Display</title>
    <style>
      html, body {
        width: 600px;
        height: 600px;
        margin: 0;
        overflow: hidden;
        background: #000;
        color: #fff;
        font-family: sans-serif;
      }
      .focusable {
        min-height: 88px;
      }
    </style>
  </head>
  <body>
    <h1>Hello Display</h1>
    <p>Backend-connected Web App</p>
    <button class="focusable">Refresh</button>
  </body>
</html>
```

That snippet follows the official constraints published in Meta's toolkit README. ([toolkit README](https://github.com/facebookincubator/meta-wearables-webapp))

## Deployment Requirements

## Confirmed Web App requirements

- **Public HTTPS hosting**
- **Standard HTML/CSS/JS**
- **600x600 viewport**
- **D-pad-compatible interaction**
- **Dark, high-contrast display design**
- **Add the app by URL in the Meta AI app**

## Practical implications

- No APK or IPA is required for the **Web App** route.
- No app store submission flow is documented in the public toolkit.
- The distribution model appears URL-based for Web Apps and release-channel/test-user-based for the DAT SDK preview.

## Limitations

## Platform limitations

- The platform is still best treated as **early-stage / preview**.
- Public evidence for a broad third-party consumer app marketplace is still weak.
- The docs/tooling are ahead of the public ecosystem maturity.

## Web App limitations

- Very small **600x600** display surface
- Interaction appears optimized for **D-pad / gesture focus**, not rich touch UI
- UI must be **glanceable**, **short**, and **high contrast**
- A Web App is still a browser app, so performance and payload size matter

## AI-specific limitations

- **FastAPI cannot render directly to the glasses**; it must feed a front-end web app
- **Custom AI output can render in your own app UI**, but there is no verified public path to replace Meta's built-in assistant response UI
- For an MVP, assume **text-first** answers only
- Keep output short enough to fit one screen or a few navigable cards

## Sensor/media limitations

- Based on the public Web App toolkit, the safest assumption is that the Web App path is best for **display UI + backend data**, not deep raw device-media access
- If you later need deeper camera/display/native capability control, expect to evaluate the **DAT SDK** path separately

## Recommended POC

## Goal

Prove that this repository can show **custom AI responses on Meta Ray-Ban Display** without betting on unstable native SDK flows.

## Proposed POC

Build a minimal system with:

- **Front-end:** one small Web App
- **Backend:** FastAPI
- **Model call:** OpenAI or another LLM provider
- **Display UX:** 1-3 short cards, D-pad navigable

## POC screens

1. **Home**
   - "Ask Assistant"
   - "Recent Response"
2. **Prompt**
   - prebuilt choices such as:
     - "Summarize what I should do next"
     - "Give me the next 3 steps"
     - "Warn me about risks"
3. **Response**
   - title
   - 2-4 bullet answer
   - optional severity badge

## POC architecture

```text
Meta Ray-Ban Display Web App
    ↓
JavaScript fetch()
    ↓
FastAPI /ask
    ↓
LLM API
    ↓
JSON response
    ↓
Web App renders concise cards
```

## Why this is the right POC

- Smallest implementation with the highest proof value
- Validates the exact question the project cares about:
  - can a custom backend drive content?
  - can custom AI output be displayed?
  - is the current platform usable now?
- Avoids overcommitting to DAT-native integration before basic display UX is proven

## Success criteria

- Web App loads on Meta Ray-Ban Display by URL
- A FastAPI endpoint returns live data
- The display renders readable response cards
- Navigation works with the display interaction model
- The output remains useful within the 600x600 constraint

## Bottom Line

**Validation result: positive.**

The Meta Wearables Web App platform is real, public enough to evaluate, and technically capable of showing custom backend-driven AI output on Meta Ray-Ban Display today. The safest conclusion is:

- **Yes** to custom web apps
- **Yes** to FastAPI as the backend
- **Yes** to rendering custom AI responses in your own display UI
- **No evidence yet** that third parties can replace Meta's built-in assistant UI
- **Proceed with a small Web App + FastAPI proof of concept**
