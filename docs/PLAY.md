# Publishing Clara on Google Play

Everything Play Console asks for, with Clara's answers. To hand this to an agent, see [PLAY-HANDOFF.md](PLAY-HANDOFF.md). Store text and graphics are in
`fastlane/metadata/android/en-US/` (the same layout F-Droid uses).

## 1. Create the app

Play Console → **Create app**: name `Clara: Private AI on Your PC`, default language English (US), **App**, **Free**.

## 2. App signing: use Clara's own key

So the Play version and the GitHub version are the **same app** (and can update each other), Play must sign with Clara's
existing key, not a new Google-generated one.

**Setup → App signing** → *Use a different key* (or *Change app signing key*) → **Export and upload a key from Java
keystore**. Play shows a command that uses its `pepk.jar` tool and an encryption key file. Download both into
`~/.clara-release/`, then run Play's command with:

- keystore: `~/.clara-release/clara-release.jks`
- alias: the `keyAlias` in `~/.clara-release/keystore.properties`

It asks for the passwords in `keystore.properties` (type them into the terminal yourself) and writes an encrypted
`output.zip` to upload. The fingerprint Play then shows for the app signing key must be:

```
28:48:6F:1D:BC:CD:F6:8B:E6:96:B1:1F:0D:20:C7:AA:F9:82:45:60:A4:D0:0C:EB:5D:BA:4B:A5:14:1D:4C:9D
```

The upload key can be the same key. Build the bundle with
`cd android && ./gradlew :app:bundleRelease` → `app/build/outputs/bundle/release/app-release.aab`.

## 3. Store listing

| Field | Value |
|---|---|
| App name | `fastlane/.../title.txt` |
| Short description | `short_description.txt` |
| Full description | `full_description.txt` |
| App icon (512×512) | `images/icon.png` |
| Feature graphic (1024×500) | `images/featureGraphic.png` |
| Phone screenshots | `images/phoneScreenshots/` |
| Category | Productivity |
| Contact email | a public address for users (required) |
| Website | https://clara.thewiderlens.info |
| Privacy policy | https://clara.thewiderlens.info/privacy |

## 4. App content

| Section | Answer |
|---|---|
| Privacy policy | URL above |
| Ads | **No**, the app has no ads |
| App access | **All or some functionality is restricted**. See "Instructions for reviewers" below |
| Content rating | Questionnaire category **All other app types**. No violence, sexual content, drugs, gambling or profanity in the app itself. "Users can interact / exchange content": **No** (only with your own assistant). Answer **Yes** to AI-generated content if asked |
| Target audience | **18 and over** |
| News app | No |
| COVID-19 / health | No |
| Data safety | See below |
| Government app | No |
| Financial features | None |
| Health | None |
| Foreground service | See below |

### Data safety

- Does your app collect or share any of the required user data types? **No.**
- Why: the app sends data only to the user's own computer (the Clara Bridge they install and run themselves). Nothing is
  sent to the developer or to third parties, and the app contains no analytics, ads or crash-reporting SDKs.
- Account creation: **No accounts.** Data deletion: uninstalling removes everything on the phone; data on the user's PC is
  under their control.

### Foreground service (`FOREGROUND_SERVICE_REMOTE_MESSAGING`)

- Type: **Remote messaging**
- Description: *"Clara keeps a live connection to the user's own computer, where their AI assistant runs, so replies,
  reminders and approval requests (e.g. 'Send this email?') arrive immediately, like a messaging app. The service runs
  only while the phone is paired and shows a persistent notification."*
- Video: a short screen recording showing the notification and an approval request arriving with the app in the background: https://www.youtube.com/watch?v=dCXVuk1OnEs

### Instructions for reviewers (App access)

> Clara is the phone app for a self-hosted AI assistant that runs on the user's own Linux PC with an NVIDIA GPU
> (https://github.com/TheWiderLensInitiative/clara). It can't be used without that PC. To review it, please use the
> demonstration video at https://www.youtube.com/watch?v=qHMkqXRiKxk, which shows pairing, chatting, an approval request and voice mode. If you need a
> live server, contact us and we'll provide a temporary pairing code and address.

## 5. Release

New personal developer accounts usually need a **closed test** first (Play Console shows the requirement, typically about 12
testers for 14 days). Create the closed testing track, upload `Clara-1.2.0.aab`, add testers by email, and promote to
production once Play allows it.
