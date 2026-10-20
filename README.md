# ESO KeePass Webhook

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

Releases: push a tag `vX.Y.Z`. CI publishes the image `ghcr.io/steadforce/eso-keepass-webhook:X.Y.Z` and
the chart `oci://ghcr.io/steadforce/charts/eso-keepass-webhook`, and creates a GitHub Release with
generated notes.

## License

[Apache 2.0](LICENSE)
