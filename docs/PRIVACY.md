# Privacy: what stays on your PC, and what doesn't

Clara is built so that **by default nothing leaves your computer**. The model, the agent, search, memory, her voice, chats,
files and the router all run locally. This page lists every exception, and every one of them is something you turn on.

## Never leaves your PC

- Your chats, Clara's memory about you, her personality and notes
- Everything she makes in her workspace (her Library)
- Your photos and files you send her
- Clara's voice is generated on your PC (Kokoro)
- The pairing tokens, API keys and account logins (encrypted with a key that only your user can read)

## Leaves your PC only when you turn it on

| Feature | What is sent | Where | You control it with |
|---|---|---|---|
| Web search & browsing | your searches and the pages she visits | the websites / search engines (through your own SearXNG) | asking her to search |
| Cloud boost | the task (e.g. coding job, picture or video prompt) | OpenRouter, then the model you picked (their privacy policies apply) | adding a key, approval per task, daily/monthly caps |
| Connectors | API calls on your behalf | that service (Google, Spotify…) | connecting the account; writes need your OK |
| Voice mode / dictation | what you say | your phone's built-in speech recognizer (often Google's; depending on the phone and its settings it may run on the device or in the cloud) | using the mic button or voice mode |
| Remote access | encrypted traffic between your phone and PC | Tailscale's coordination servers (not your data) | running `setup/tailscale.sh` |
| Installation & updates | downloads of models and software | GitHub, Hugging Face, PyPI, npm, Docker Hub | running the installer |

The Clara project has no servers, analytics or telemetry, and nothing you do is used to train anything.

## Passwords

Website passwords live **only on your phone**, encrypted with Android's keystore. When Clara needs to sign in, your phone
asks for your fingerprint, encrypts that one login for that one sign-in, and the browser fills it in. Clara never sees it,
and the PC never stores it.

## Safety rules Clara can't change

Clara runs as her own Linux user in a sandbox: she can't see your home folder, can't use sudo, and her safety rules
(**Guardian**) are files she can read but not modify. Sending, deleting, buying, installing, network and admin actions
ask you on your phone first. Emails she reads are treated as untrusted: instructions inside them are ignored.

## The Clara phone app

The app talks **only to your own PC** (your Clara Bridge), over your home Wi-Fi or your private Tailscale network. It
contains no analytics, ads, crash reporting or tracking libraries, and it never contacts the Clara project or any server of
ours: we don't run any.

| On your phone | Why | Where it goes |
|---|---|---|
| Your PC's address and the pairing token | to reach your Clara | stays on the phone (app storage) |
| Saved website logins (vault) | so Clara can sign in without seeing them | stays on the phone, encrypted with the Android keystore; one login is sealed for your PC only when you approve a sign-in |
| Messages, photos and files you send | to talk to Clara | your PC only |
| Microphone (voice mode, dictation) | to hear you | the phone's own speech recognizer turns speech into text; the text goes to your PC |
| Notifications | replies, reminders, approval requests | shown on the phone |
| Your OpenRouter key, if you add one | cloud boost | your PC, which stores it encrypted |

Temporary voice clips and previews live in the app's cache and are deleted by Android as needed. Uninstalling the app
removes everything it stored on the phone. Data on your PC is yours to keep or delete (`~/.local/share/clara`).

Children: Clara is not directed at children under 13.

Changes to this policy are published in this file, with history at
https://github.com/TheWiderLensInitiative/clara/commits/main/docs/PRIVACY.md

## Contact

The Wider Lens Initiative Project: questions and requests at https://github.com/TheWiderLensInitiative/clara/issues
(security problems: see [SECURITY.md](../SECURITY.md)).
