# Meta Ray-Ban Display SDK Integration Findings

Research date: 2026-06-01

## Short answer

Meta now appears to offer **two real developer paths** for the Meta Ray-Ban Display platform:

1. **Native mobile apps** via the **Meta Wearables Device Access Toolkit (DAT)** for iOS and Android.
2. **Hosted web apps** for the display using standard **HTML/CSS/JavaScript**.

The current state looks like **publicly documented developer preview**, not full GA, and not obviously invite-only.

---

## 1) Can third-party developers send custom text to the Meta Ray-Ban Display?

**Yes.**

Current evidence says third-party developers can send custom display content to the glasses:

- The official iOS DAT sample app is explicitly named **Display Access App** and says it demonstrates **sending visual content to Meta Ray-Ban Display glasses**.[^ios-display-readme]
- Its sample code uses a display module with primitives including `Text`, `Image`, `Button`, `FlexBox`, and `VideoPlayer`.[^ios-display-code]
- Meta’s web-app toolkit repo describes **web apps rendered on Meta Ray-Ban Display glasses**.[^webapp-readme]

### Practical interpretation

- **Native path:** yes, through DAT display APIs.
- **Web path:** yes, through a hosted web app rendered on the display.
- **Notification path:** not the primary/documented developer UI path.

---

## 2) Can web apps run on the display?

**Yes.**

The official Meta web-app toolkit repo says:

- Web apps are **standard HTML/CSS/JavaScript applications rendered on Meta Ray-Ban Display glasses**.[^webapp-readme]
- They are added from the Meta AI app using a **public HTTPS URL**.[^webapp-readme]
- The repo frames this as the glasses web-app path and links to Meta’s Wearables Developer Center web-app docs.[^webapp-readme]

### Important nuance

These are not arbitrary browser tabs running like a normal phone browser UI. They are constrained display web apps with device-specific design rules.

---

## 3) Can iOS apps use the Meta Wearables Device Access Toolkit to display text, images, lists, buttons, or video?

**Yes, based on the official iOS sample app.**

The clearest evidence is the official sample at:

- `facebook/meta-wearables-dat-ios`
- `samples/DisplayAccess`

That sample shows:

- **Text** via `Text(...)`[^ios-display-code]
- **Images** via `Image(...)`[^ios-display-code]
- **List-like/tutorial menus** composed from `FlexBox` rows/columns[^ios-display-code]
- **Buttons** via `Button(...)`[^ios-display-code]
- **Video** via `VideoPlayer(...)` with an MP4 provider[^ios-display-code]

### Conclusion

For iOS specifically, the answer is **yes**: current official samples demonstrate text, images, list-style UI, buttons, and video on the display.

---

## 4) Is access public, invite-only, or developer preview?

**Best current characterization: publicly documented developer preview.**

Why:

- The official iOS and Android DAT repos are public on GitHub and both state: **“The Wearables Device Access Toolkit is in developer preview.”**[^ios-readme][^android-readme]
- Those READMEs say developers can access the SDK and docs, create organizations, and create release channels for test users.[^ios-readme][^android-readme]
- The web-app repo is also public and links to Meta’s web-app developer docs.[^webapp-readme]

### Working interpretation

- **Not GA/stable:** still preview.
- **Not obviously invite-only:** public repos and docs exist.
- **Operationally gated:** you still need Meta account/app setup, device access, and likely release-channel/test-user setup for native app distribution.

---

## 5) What setup steps are required?

## Native iOS / DAT path

From the official iOS DAT repo and DisplayAccess sample:

1. Add the iOS SDK via **Swift Package Manager**.[^ios-readme]
2. Configure the app’s `Info.plist` under the `MWDAT` key.[^ios-readme][^ios-info]
3. Provide:
   - app link URL scheme
   - Meta app ID
   - client token
   - team ID
   - `DAMEnabled = true` in the sample[^ios-info]
4. Enable required permissions/capabilities like Bluetooth, local network, external accessory support, and background modes.[^ios-info]
5. Turn on **Developer Mode** in the Meta AI app for the sample flow.[^ios-display-readme]
6. Register the app, connect the glasses, and update firmware / glasses app if prompted.[^ios-display-readme]
7. Test on a physical Meta Ray-Ban Display device.[^ios-display-readme]

## Native Android / DAT path

From the official Android DAT repo:

1. Add the GitHub Packages Maven source.
2. Provide a `GITHUB_TOKEN` with `read:packages`.
3. Add DAT dependencies in Gradle.
4. Configure the required manifest metadata, including the Meta application ID.[^android-readme]

## Web-app path

From the official Meta web-app toolkit repo:

1. Build a standard HTML/CSS/JS app.[^webapp-readme]
2. Test locally in a desktop browser.[^webapp-readme]
3. Deploy it to a **public HTTPS URL**.[^webapp-readme]
4. Open the **Meta AI app** on the phone.
5. Go to **Devices → Display Glasses settings → App connections → Web apps**.
6. Add the web app name and URL.[^webapp-readme]

---

## 6) What are the limitations?

## Platform maturity

- DAT is still **developer preview**.[^ios-readme][^android-readme]
- Expect evolving APIs, docs, and distribution rules.

## Web-app UI constraints

The official web-app toolkit README calls out:

- **600x600 px viewport**
- **D-pad navigation only**
- **Dark backgrounds** preferred because black is transparent on the additive display
- **High contrast** for readability
- Interactive elements need a `.focusable` class[^webapp-readme]

## Deployment/ops constraints

- Web apps must be hosted at a **publicly available HTTPS URL**.[^webapp-readme]
- Native distribution appears aimed at **organizations, release channels, and test users**, not mass public store-style distribution yet.[^ios-readme][^android-readme]

## Device/app constraints

- You need the **Meta AI app**, a supported device, and likely current firmware / glasses app versions.[^ios-display-readme]
- The sample explicitly warns that firmware or the glasses-side app may need updates before sessions can start.[^ios-display-readme]

## Practical UX limitation

This is a **small glanceable display**, not a full general-purpose screen. The current examples and design rules strongly favor compact cards, step flows, buttons, and short interactions.

---

## 7) Can Python backend output be routed to the display through a web app or mobile app?

**Yes, most likely.**

## Through a web app

This is the most straightforward route.

The official web-app repo explicitly includes a skill called **`connect-api`** for connecting to **REST/WebSocket APIs**.[^webapp-readme]

That means a practical architecture is:

`Python backend -> HTTPS/WebSocket API -> web app -> Meta Ray-Ban Display`

## Through a mobile app

Also yes.

A native iOS or Android app can fetch output from a Python backend and then render that output through DAT display APIs.

### Recommended interpretation

- **Web app:** easiest for a quick POC.
- **Native app:** best if you need tighter phone integration, richer state management, or device-specific native flows.

---

## 8) Can iPhone notifications be used as a fallback display path?

**Maybe as a crude fallback, but not as the primary or best-supported developer path.**

What seems true from current public info:

- Meta help/search results suggest the glasses can integrate with phone notifications/messages/calls once paired through the Meta AI app.[^meta-help-search]
- But notifications are a **consumer feature**, not the documented display-SDK path.
- I did **not** find current official developer docs showing a supported API for “send arbitrary formatted custom app UI to display via iPhone notifications.”

### Practical conclusion

- **For plain fallback alerts:** possibly useful if the glasses mirror selected iPhone notifications in practice.
- **For reliable custom UI:** no, use DAT or the web-app path instead.
- **For this project:** treat notifications as a backup experiment, not the main integration design.

---

## 9) What example repos or docs exist?

## Official/public repos

1. **iOS DAT SDK**
   - `https://github.com/facebook/meta-wearables-dat-ios`[^ios-readme]

2. **Android DAT SDK**
   - `https://github.com/facebook/meta-wearables-dat-android`[^android-readme]

3. **Meta web-app toolkit**
   - `https://github.com/facebookincubator/meta-wearables-webapp`[^webapp-readme]

## Particularly useful examples

- `facebook/meta-wearables-dat-ios/samples/DisplayAccess` — strongest evidence for real display UI support on iOS.[^ios-display-readme][^ios-display-code]
- `facebookincubator/meta-wearables-webapp/examples/snake` — example web app for the display path.[^webapp-examples]

## Official doc entry points referenced by the official repos

- Wearables Developer Center: `https://wearables.developer.meta.com/`
- DAT docs: `https://wearables.developer.meta.com/docs/develop/`
- Web-app docs: `https://wearables.developer.meta.com/docs/develop/webapps`

Note: those official sites were not directly fetchable from this sandbox, but they are linked from Meta/Facebook-owned public repositories above.

---

## 10) What is the fastest proof-of-concept for this project?

**Fastest POC: a tiny hosted web app backed by a Python API.**

## Recommended POC architecture

1. Build a minimal web app with:
   - one screen
   - large high-contrast text
   - optional one or two D-pad-selectable buttons
2. Host it at a public HTTPS URL.
3. Add it to the glasses through **Meta AI app → Devices → Display Glasses settings → App connections → Web apps**.[^webapp-readme]
4. Have the web app fetch from a Python backend endpoint such as:
   - `/latest`
   - `/status`
   - `/caption`
5. Render backend text onto the display.

## Why this is the fastest

- No native iOS or Android build pipeline required.
- No Swift/Kotlin UI work required.
- Cleanest way to route Python output onto the display.
- The official web-app tooling already assumes REST/WebSocket integrations.[^webapp-readme]

## Best fallback POC

If the web-app route is blocked on-device, the next fastest POC is:

- start from `facebook/meta-wearables-dat-ios/samples/DisplayAccess`
- replace the tutorial content with backend-driven text/cards
- fetch JSON from the Python backend and map it to DAT display views

---

## Recommended decision for this repository

For this project, the best near-term plan is:

1. **Primary path:** web app + Python backend.
2. **Secondary path:** iOS DAT sample fork if native integration becomes necessary.
3. **Do not rely on notifications** as the core display mechanism.

---

## Bottom line

- **Q1:** Yes, third parties can send custom display content.
- **Q2:** Yes, web apps can run on the display.
- **Q3:** Yes, iOS DAT can display text, images, list-style layouts, buttons, and video.
- **Q4:** Publicly visible **developer preview**.
- **Q5:** Setup requires Meta AI app/device setup, developer mode or app registration, SDK/web-app configuration, and physical device testing.
- **Q6:** Preview-state platform, small constrained UI, 600x600 web viewport, D-pad-first navigation, public HTTPS hosting for web apps, and release/test-user friction for native apps.
- **Q7:** Yes, Python output can be routed through either web or native app paths.
- **Q8:** Notifications are only a weak fallback, not the recommended integration route.
- **Q9:** Official iOS, Android, and web-app repos now exist.
- **Q10:** Fastest POC is a tiny hosted web app that fetches from a Python backend.

---

## Sources

[^ios-readme]: Facebook official repo, `facebook/meta-wearables-dat-ios`, README: https://github.com/facebook/meta-wearables-dat-ios
[^android-readme]: Facebook official repo, `facebook/meta-wearables-dat-android`, README: https://github.com/facebook/meta-wearables-dat-android
[^ios-display-readme]: Official iOS sample README, `samples/DisplayAccess/README.md`: https://github.com/facebook/meta-wearables-dat-ios/tree/main/samples/DisplayAccess
[^ios-display-code]: Official iOS sample code, `samples/DisplayAccess/DisplayAccess/Samples/CarMaintenanceDisplay.swift`: https://github.com/facebook/meta-wearables-dat-ios/blob/main/samples/DisplayAccess/DisplayAccess/Samples/CarMaintenanceDisplay.swift
[^ios-info]: Official iOS sample `Info.plist`: https://github.com/facebook/meta-wearables-dat-ios/blob/main/samples/DisplayAccess/DisplayAccess/Info.plist
[^webapp-readme]: Meta/Facebook Incubator repo, `facebookincubator/meta-wearables-webapp`, README: https://github.com/facebookincubator/meta-wearables-webapp
[^webapp-examples]: Web-app examples directory: https://github.com/facebookincubator/meta-wearables-webapp/tree/main/examples
[^meta-help-search]: Meta help pages surfaced by current search results for Meta Ray-Ban Display usage/setup, including `https://www.meta.com/help/ai-glasses/693194947052406/` and `https://www.meta.com/help/ai-glasses/1864740664283499/`
