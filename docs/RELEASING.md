# Releasing

Builds are published from the **Build SpinUI components and Windows release**
workflow, run manually (Actions → Run workflow). Three inputs matter:

| Input | Meaning |
|---|---|
| `publish_release` | Attach the built assets to a GitHub release. Leave it off to build and verify without publishing anything. |
| `release_tag` | The tag to create or update. |
| `prerelease` | On by default. Publishes a release candidate. |

## Release candidates

A candidate is published as a GitHub pre-release, which is what keeps it out of
everyone else's hands: both in-app updaters skip `draft` and `prerelease`
releases, so a candidate is never offered to anyone. Install it yourself, by
hand, and run it.

Candidate tags must carry a semver prerelease suffix:

    v0.3.5-rc.1

The workflow refuses to publish a candidate under a bare `v0.3.5`, and refuses
to publish a full release under a tag carrying a suffix. Both refusals exist
for the same reason: the updaters compare semver prerelease components, so a
candidate published as `v0.3.5` would burn the tag the real release needs, and
a full release tagged `-rc.1` would be permanently invisible to updaters.

Iterate with `-rc.2`, `-rc.3`, and so on. Each is its own release, so an
earlier candidate stays downloadable while a newer one is tested.

## Promoting to a real release

Run the workflow again with `prerelease` **off** and the bare tag:

    v0.3.5

That publishes a full release, marks it Latest, and is the point at which
updaters start offering it. Nothing is copied from the candidate: the release
is built fresh from whatever `main` points at, so promote only a commit that a
candidate was cut from and tested at.

## What a Linux install actually updates

The Linux AppImage has **no self-update**. The app updater replaces a portable
Windows `Loremaster.exe` and does nothing on Linux, so a new AppImage is always
a manual download. The SpinUI **skin** updater does run on Linux, and it
follows full releases only, exactly like the app updater.

That is why testing a candidate on Linux is a manual install by design.
