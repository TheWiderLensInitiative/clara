# Handoff: put Clara on Google Play

For the agent helping The Wider Lens Initiative Project publish the Clara app on Google Play. Read
[PLAY.md](PLAY.md) (every Play Console form, with Clara's answers) and [PRIVACY.md](PRIVACY.md) first.

## What's already done

| Item | Where |
|---|---|
| Package registered for Android developer verification (Play Console, account "DevIgnite") | `info.thewiderlens.clara`, key verified |
| Store text: title, short and full description | `fastlane/metadata/android/en-US/*.txt` |
| Icon 512×512, feature graphic 1024×500 | `fastlane/metadata/android/en-US/images/` |
| 6 phone screenshots (1080×2160, 2:1 as Play requires) | `fastlane/metadata/android/en-US/images/phoneScreenshots/` |
| Release notes per version | `fastlane/metadata/android/en-US/changelogs/<versionCode>.txt` |
| Signed app bundle, version 1.3.1 (versionCode 7) | **not in git**: `~/Desktop/TheWiderLens/release-files/Clara-1.3.1.aab` on the project owner's PC |
| Privacy policy | `docs/PRIVACY.md` (Play needs a public URL; see task W1) |
| Videos: promo, reviewer demo, foreground-service demo | `media/google-play/` (see "Videos" below) |

The `fastlane/metadata/android` folder uses fastlane's layout, so `fastlane supply` can upload it as is.

## Rules

- **Never** put a keystore, `keystore.properties`, a Google service-account JSON key or any password in the repo, a chat,
  a web page or a log. The signing key lives only in `~/.clara-release/` on the owner's PC.
- The owner signs in to Google themselves. Don't ask for their password.
- Use **Clara's own signing key** for Play App Signing (PLAY.md §2), never a Google-generated one; otherwise the Play
  app and the GitHub app can't update each other. The fingerprint must be
  `28:48:6F:1D:BC:CD:F6:8B:E6:96:B1:1F:0D:20:C7:AA:F9:82:45:60:A4:D0:0C:EB:5D:BA:4B:A5:14:1D:4C:9D`.
  Copy it from here, or read it with `apksigner verify --print-certs`; don't retype it.

## Part 1: the owner, in Play Console (needs their login; about 30 minutes)

Google only allows these by hand. Walk the owner through them using PLAY.md, or fill the forms in their signed-in browser
if you can control one:

1. **Create app**: name `Clara: Private AI on Your PC`, App, Free.
2. **App signing**: upload Clara's key with Google's PEPK tool (PLAY.md §2). The owner runs that command on their PC.
3. **App content**: privacy policy URL, ads (none), app access (reviewer instructions), content rating, target audience
   (18+), data safety (no data collected), foreground service declaration. All answers are in PLAY.md §4.
4. **Store listing**: paste the text and upload the images, or let Part 2 do this.
5. **First upload**: Testing → **Closed testing** → create a track, upload `Clara-1.3.1.aab`, add testers. The very
   first bundle must be uploaded by hand; the API can't create an app.

## Part 2: the agent, automated (after Part 1, step 5)

**Setup, once (the owner clicks; about 10 minutes):**
1. Google Cloud console → create a project → enable **Google Play Android Developer API**.
2. Create a **service account** and download its JSON key to `~/.clara-release/play-service-account.json` (never into
   the repo).
3. Play Console → **Users and permissions** → invite the service account's email → permissions for the Clara app:
   *Release to testing tracks*, *Manage store presence* (add *Release to production* later).

**Then the agent can run, from the repo root:**

```bash
# store text, icon, feature graphic, screenshots, changelogs
fastlane supply --package_name info.thewiderlens.clara --json_key ~/.clara-release/play-service-account.json \
  --metadata_path fastlane/metadata/android --skip_upload_aab --skip_upload_apk

# a new release to the closed test (bump versionCode in android/app/build.gradle.kts first, then:
#   cd android && ./gradlew :app:bundleRelease)
fastlane supply --package_name info.thewiderlens.clara --json_key ~/.clara-release/play-service-account.json \
  --aab android/app/build/outputs/bundle/release/app-release.aab --track alpha --skip_upload_metadata
```

(`alpha` is the API's name for the closed testing track; `production` once Play allows it.) Each new version must also
be published on GitHub Releases with the same versionCode, so both channels stay in step.

## Videos

Play only accepts **YouTube links**, not files. Upload each video from `media/google-play/` to the project's YouTube
channel, then paste the links:

| File | YouTube visibility | Where the link goes |
|---|---|---|
| `clara-promo.mp4` (68 s, landscape) | Public | Store listing → **Video**; also `fastlane/metadata/android/en-US/video.txt` so `fastlane supply` keeps it |
| `clara-reviewer-demo.mp4` (2:58, portrait) | Unlisted | App content → **App access** instructions (replace `<VIDEO LINK>` in PLAY.md) |
| `clara-foreground-service.mp4` (43 s, portrait) | Unlisted | App content → **Foreground service permissions** → video link |

The videos are built from phone screen recordings by `tools/play_videos.py` (cut list, captions and timing are at the
bottom of that file); rerun it after recording new clips.

## Part 3: the website (clara.thewiderlens.info)

- **W1. Privacy policy page** at `https://clara.thewiderlens.info/privacy`, made from `docs/PRIVACY.md` (keep it in step
  with that file). Then use that URL in Play Console instead of the GitHub link.
- **W2. Join the beta.** Done: https://clara.thewiderlens.info/beta. Testers join the Google Group
  **clara-beta-testers@googlegroups.com** (https://groups.google.com/g/clara-beta-testers). In Play Console, add that
  group as the closed testing track's tester list, then put Play's opt-in link on the beta page and email it to the group.
- **W3. Download section**: keep the GitHub link (`https://github.com/TheWiderLensInitiative/clara/releases/latest`)
  and add the official "Get it on Google Play" badge only once the app is public.
- **W4. Contact**: clara@thewiderlens.info, on Play (store listing contact email), the site, and the privacy policy.

## Decisions for the owner

- ~~Public developer name~~ Decided: the app is credited as **"Created by DevIgnite × The Wider Lens Initiative Project"** (store description, README, video end cards). The Play developer account stays DevIgnite; the license's copyright holder stays The Wider Lens Initiative Project.
- ~~Public contact email~~ Decided: clara@thewiderlens.info (W4).
- ~~Beta testers~~ Recruiting through the beta page and the Google Group (W2).
