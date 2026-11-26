# ESO KeePass Webhook

[![CI](https://github.com/steadforce/eso-keepass-webhook/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/steadforce/eso-keepass-webhook/actions/workflows/ci.yaml)
[![Nightly patch release](https://github.com/steadforce/eso-keepass-webhook/actions/workflows/nightly-patch-release.yaml/badge.svg?branch=main)](https://github.com/steadforce/eso-keepass-webhook/actions/workflows/nightly-patch-release.yaml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](pyproject.toml)
[![Release](https://img.shields.io/github/v/release/steadforce/eso-keepass-webhook)](https://github.com/steadforce/eso-keepass-webhook/releases)

Serves entries from a [KeePass](https://keepass.info/) database to the
[External Secrets Operator](https://external-secrets.io/) (ESO) through its
[webhook provider](https://external-secrets.io/latest/provider/webhook/), so they can be used as
Kubernetes Secrets.

```
ExternalSecret ──▶ ESO ──HTTP──▶ eso-keepass-webhook ──▶ database.kdbx (mounted Secret)
                    │
                    └──▶ Kubernetes Secret
```

- Reads KDBX 3.1 and 4.x, unlocked with a password and/or key file
- Fields, custom fields, field references and attachments
- Reloads the database and auth token when they change, without a restart
- Distroless image for `linux/amd64` and `linux/arm64`, and a Helm chart

## Quick start

Requires ESO in the cluster. Put the database and its master password into a Secret, then install
the chart:

```bash
kubectl create namespace keepass
kubectl -n keepass create secret generic keepass-database \
  --from-file=database.kdbx=./secrets.kdbx --from-file=password=./password.txt
helm install eso-keepass-webhook oci://ghcr.io/steadforce/charts/eso-keepass-webhook -n keepass
```

It deploys the webhook, has ESO generate an auth token and creates a `ClusterSecretStore` named
`keepass`. See the [chart's README](charts/eso-keepass-webhook/README.md) for all options.

## Usage

`remoteRef.key` is the path of the entry, `remoteRef.property` the field:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: postgres
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: keepass
  target:
    name: postgres
  data:
    - secretKey: password
      remoteRef:
        key: apps/postgres/admin   # group "apps" › group "postgres" › entry "admin"
        property: password
    - secretKey: api-key
      remoteRef:
        key: apps/postgres/admin
        property: API KEY          # custom field
  # Or every field of the entry at once:
  # dataFrom:
  #   - extract:
  #       key: apps/postgres/admin
```

- **Paths** start below the root group: `Entry`, `Group/Entry`, `Group/Subgroup/Entry`.
  Titles and group names must not contain `/`.
- **Fields** are `username`, `password`, `url`, `notes` and any custom field. Field references
  like `{REF:P@I:…}` are resolved.
- **Attachments** are returned by file name, byte for byte: `property: tls.crt`.
- Without `property`, all fields of the entry are returned as JSON; attachments are not included.
- A path, field or attachment that matches more than once is an error.

## API

| Request | Response |
|---|---|
| `GET /v1/secret?path=<path>&property=<name>` | Raw field value, or attachment content |
| `GET /v1/secret?path=<path>` | JSON object with all fields |
| `GET /healthz` | `ok` (no auth) |

`/v1/secret` requires `Authorization: Bearer <token>`. Status codes: `400` missing path,
`401` bad token, `404` entry, field or attachment not found (ESO treats this as "secret deleted"),
`409` ambiguous path or name, `500` broken field reference.

## Configuration

| Variable | Description |
|---|---|
| `KDBX_PATH` | Database file (required) |
| `KDBX_PASSWORD_FILE` | File with the master password (re-read on reload) |
| `KDBX_PASSWORD` | Master password; prefer `KDBX_PASSWORD_FILE` |
| `KDBX_KEYFILE` | Key file |
| `KDBX_RELOAD_INTERVAL` | Seconds between checks for a changed database, password or key file, default `10` |
| `AUTH_TOKEN_FILE` / `AUTH_TOKEN` | Bearer token clients must send (required); the file is re-read when it changes |
| `PORT` | Listen port, default `8080` |
| `LOG_LEVEL` | Default `INFO` |

At least one of password or key file is required. A trailing newline in secret files is ignored.

A changed database, password or key file is loaded in the background and replaces the previous
version once it has loaded; until then, and if loading fails, the previous version is served.
Every load is logged with its duration. Use KDBX 4 with Argon2 (KeePassXC's default): AES-KDF with
many rounds can take minutes to load.

## Security notes

- Anyone holding the auth token can read **every** entry in the database. Use a database that
  contains only what the cluster needs.
- The chart's NetworkPolicy lets only ESO's controller reach the webhook, and blocks all its
  outgoing traffic. It assumes ESO's defaults (namespace `external-secrets`); adjust
  `networkPolicy.from` otherwise, or ESO cannot reach the webhook.
- Traffic between ESO and the webhook is plain HTTP. To encrypt it, use a CNI with encryption
  or a service mesh with mTLS.
- Loading the database allocates the KDF's memory cost (KeePassXC default: 64 MiB). Raise the
  memory limit if your database uses a higher setting.

## Development

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check && uv run mypy

# Chart: tests, and the README's values table from values.yaml
helm lint --strict charts/eso-keepass-webhook
docker run --rm -u "$(id -u)" -v "$PWD/charts:/helm-docs" jnorwood/helm-docs:v1.14.2
docker run --rm -u "$(id -u)" -e HELM_CACHE_HOME=/tmp/helm/.config -v "$PWD:/apps" -w /apps \
  helmunittest/helm-unittest --strict charts/eso-keepass-webhook

# Run locally
KDBX_PATH=./test.kdbx KDBX_PASSWORD=... AUTH_TOKEN=dev uv run eso-keepass-webhook
curl -H 'Authorization: Bearer dev' 'localhost:8080/v1/secret?path=Group/Entry&property=password'

# Build the image
docker buildx build --platform linux/amd64,linux/arm64 -t eso-keepass-webhook .
```

## Releases

Tags are semantic versions with a `v` prefix (`v1.2.3`). Every release publishes the image
`ghcr.io/steadforce/eso-keepass-webhook:1.2.3` (also `1.2`), the chart
`oci://ghcr.io/steadforce/charts/eso-keepass-webhook` and a GitHub release with generated notes, a signed
SBOM and a card in the Teams release channel (secret `STEADOPS_RELEASE_MS_TEAMS_WEBHOOK`). The notes list the merged
pull requests grouped by label as configured in [`.github/release.yaml`](.github/release.yaml): Renovate pull
requests carry the label `dependencies`. Label a pull request `skip-changelog` to leave it out.

- **Manual release (minor, major, first stable release):** push a tag `vX.Y.Z` on `main`. Tags with a hyphen
  (`v1.0.0-rc.1`) are published as prereleases. A release that was published by hand in the GitHub UI works too (it creates
  the tag): CI keeps its text and only attaches the SBOM.
- **Nightly patch release:** [`nightly-patch-release.yaml`](.github/workflows/nightly-patch-release.yaml) runs every
  night (02:17 UTC) and can be started by hand (`dry_run` is on by default and only reports in the run summary what it
  would do). If `uv.lock`, `.python-version` or the `Dockerfile` changed since the newest stable tag, it releases the next patch
  version from the head of `main`. Changes of `src/`, `tests/`, `charts/` and `.github/` do not trigger a release, but a
  dependency release contains them if they were merged since the last release. It does nothing as long as there is no
  stable tag (prereleases are ignored).

Release tags have to be `vX.Y.Z` (or `vX.Y.Z-rc.1` for a prerelease, valid SemVer without build metadata); a pushed tag of another form
such as `v1` or `v1.2.3-rc..1` fails in the first job and publishes nothing. So does a stable tag that is older than the newest
release (for example a re-run of an older tag run), because it would overwrite the shared image tags `X.Y` and `latest`.

Safeguards against two releases of the same version or an older release overwriting a newer one (the image tags `X.Y` and `latest` are
shared by several versions): all release runs, tag pushes and nightly releases alike, share one lock and never publish at the same time.
A nightly release refuses to publish when a tag of its version exists or when a newer stable release appeared after the plan was made.
This is checked at the start, again right before the image is pushed, and again before the release is created. The release is only
created when no tag of that version exists, and afterwards its tag has to point to the built commit. A nightly release does not move
the `main` image tag.

Renovate merges patch and digest updates of the Python dependencies and the `Dockerfile`, and all GitHub Actions updates,
three days after their release once the checks pass. Minor and major updates of dependencies stay manual.

### Image scanning and signing

Every image that is pushed (releases and `main`) is scanned and signed; pull request images are not pushed.

- **Trivy scan before the push:** the image is built once, scanned (operating system packages and Python libraries) and only
  pushed when the scan passes. The build fails on `HIGH` and `CRITICAL` vulnerabilities that already have a fixed version.
  Pull requests are only reported, so the update that fixes a finding can still be merged. A finding that has to be accepted
  goes into `.trivyignore` with a comment and an expiry date (`CVE-... exp:2026-12-31`). The scan covers the `linux/amd64`
  image; the `linux/arm64` image differs only in the architecture-specific wheels, which are pinned by hash to the same versions.
- **Cosign keyless signature:** after the push the digest of the multi-arch image is signed with the identity of the workflow
  (GitHub OIDC, recorded in the public Rekor log) and verified in the same run. There is no key or secret to manage.
- **Pinned scan tools:** `trivy-action` and `cosign-installer` are pinned to commit SHAs (most `trivy-action` tags were rewritten
  to malicious commits in March 2026). The Trivy version is set once in `SCANNER_TRIVY_VERSION` in `ci.yaml`; Renovate updates it
  three days after release.

Verify an image before using it:

```bash
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github\.com/steadforce/eso-keepass-webhook/\.github/workflows/ci\.yaml@' \
  ghcr.io/steadforce/eso-keepass-webhook:X.Y.Z
```

### SBOM

Every pushed image gets a CycloneDX SBOM (JSON) of its operating system packages and Python libraries.

- **Signed attestation on the image:** attached to the image digest with `cosign attest` (same identity as the signature):

  ```bash
  cosign verify-attestation --type cyclonedx \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com \
    --certificate-identity-regexp '^https://github\.com/steadforce/eso-keepass-webhook/\.github/workflows/ci\.yaml@' \
    ghcr.io/steadforce/eso-keepass-webhook:X.Y.Z | jq -r '.payload | @base64d | fromjson | .predicate' > sbom.cdx.json
  ```

- **Asset of the GitHub release:** `eso-keepass-webhook-<version>.cdx.json`.
- Scan it later for new vulnerabilities: `trivy sbom sbom.cdx.json`.

## License

[Apache 2.0](LICENSE)
