# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

## What is signed

Only the Windows release files that GitHub Actions builds from this repository's source are signed. That is `Kanjo.exe` and the Velopack installers `KanjoApp-win-x64-Setup.exe` and `KanjoApp-win-arm64-Setup.exe`, built by the `windows-app` job in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) when a `v*` tag is pushed. The bundled official Python embeddable distribution is upstream software and is not signed under this project's certificate.

Each signing request is approved by hand before a release is published.

## Team roles

- Committers and reviewers: [mammut001](https://github.com/mammut001)
- Approvers: [mammut001](https://github.com/mammut001)

Every change from someone outside the team (for example a pull request) is reviewed by a committer before it is merged. All team members use multi-factor authentication for GitHub and SignPath.

## Privacy policy

Kanjo reads AI coding agents' local log files on your computer and computes usage from them on the device. It does not send that data anywhere unless you turn on a feature that does:

- **Publish to website** (off by default): pushes aggregate numbers to a git repository you choose.
- **Family usage** (off by default): sends aggregate numbers to a family server whose address you enter.

It also makes these requests by itself:

- **Subscription quota:** reads your remaining quota from the services you are already signed in to (Anthropic, OpenAI, xAI), using the credentials those tools stored on your computer. The credentials go only to the service that issued them. Set `KANJO_NO_NETWORK=1` to turn this off.
- **Updates (Windows app):** checks GitHub Releases for this repository for a newer version. No usage data is sent.

Project names, file paths, conversation contents and account emails never leave your computer. Kanjo has no analytics or telemetry.

Uninstall: Windows Settings → Apps → Kanjo. Your data in `%APPDATA%\Kanjo` and `%LOCALAPPDATA%\kanjo` is kept; delete those folders to remove it.
