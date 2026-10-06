# Privacy Manifest

Use this reference when a task adds storage, file access, required-reason API usage, or new third-party SDKs.

## Baseline

- The minimal scaffold does not include `PrivacyInfo.xcprivacy` yet.
- Add or update the privacy manifest when the project starts using covered APIs or SDKs that require declarations for App Store submission.

## Checkpoints

- Review required-reason API categories when introducing file metadata access, disk-space inspection, boot-time access, keyboard-state access, or user-defaults-driven patterns.
- Review third-party SDK privacy requirements before adding new SDK dependencies.
- Keep privacy-manifest updates in the same change as the new API or SDK usage.
