#!/usr/bin/env bash
# Prepare the OpenSearch index sidecar for local development (ADR-0011, CP-22). Run once, after
# scripts/dev-env.sh; --force replaces everything (and the index must then be rebuilt).
#
# Writes, never committed:
#   deploy/opensearch/generated/certs/   a private CA and the node's certificate and key, owned
#                                        by the container's user (uid 1000), mode 600
#   deploy/opensearch/generated/admin/   the admin certificate and key (the security plugin's
#                                        admin DN, for securityadmin.sh and the tests); never
#                                        mounted into the running node
#   deploy/opensearch/generated/security/ the security plugin's configuration: the committed
#                                        files in deploy/opensearch/security plus
#                                        internal_users.yml with bcrypt hashes of two fresh
#                                        passwords
#   deploy/index.env                     for the api: the index URL, the read-only
#                                        regwatch_search user and its password, and the CA
#                                        (base64)
#   deploy/index-worker.env              for the worker: the same with the regwatch_indexer user
# The passwords never appear on a command line: they reach the hashing container in a mode-600
# file.
#
# The security plugin reads these files only when it creates its security index, so --force
# refuses while the index-data volume exists: stop the sidecar and remove that volume first
# (docker compose --profile index down; docker volume rm regwatch_index-data), then rebuild the
# index (python -m regwatch.search.tasks).
set -euo pipefail
umask 077
root="$(cd "$(dirname "$0")/.." && pwd)"
image="opensearchproject/opensearch@sha256:3bf4fe26aeb9f7b03c0ebcb1302bb24e855ee6b89fd926d26a71a83ef6f7e076"
# INDEX_SETUP_OUT and INDEX_SETUP_ENV let tests prepare a throwaway sidecar elsewhere.
out="${INDEX_SETUP_OUT:-$root/deploy/opensearch/generated}"
envfile="${INDEX_SETUP_ENV:-$root/deploy/index.env}"
workerfile="${envfile%.env}-worker.env"
volume="${INDEX_SETUP_VOLUME:-regwatch_index-data}"

if [[ "${1:-}" != "--force" && -d "$out/certs" && -f "$envfile" ]]; then
  echo "the index sidecar is already prepared; pass --force to recreate it"
  exit 0
fi
if [[ -z "${INDEX_SETUP_OUT:-}" ]] && docker volume inspect "$volume" >/dev/null 2>&1; then
  echo "the volume $volume holds the old security index, so new passwords would not load;" >&2
  echo "run: docker compose --profile index down && docker volume rm $volume" >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
subject() { echo "/O=regwatch/CN=$1"; }
openssl req -x509 -newkey rsa:3072 -nodes -days 825 -subj "$(subject regwatch-index-ca)" \
  -keyout ca-key.pem -out ca.pem -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
issue() {  # name, extensions
  openssl req -newkey rsa:3072 -nodes -subj "$(subject "$1")" -keyout "$1-key-pkcs1.pem" \
    -out "$1.csr" 2>/dev/null
  openssl pkcs8 -topk8 -nocrypt -in "$1-key-pkcs1.pem" -out "$1-key.pem"
  printf '%s\n' "$2" > "$1.ext"
  openssl x509 -req -in "$1.csr" -CA ca.pem -CAkey ca-key.pem -CAcreateserial -days 825 \
    -sha256 -extfile "$1.ext" -out "$1.pem" 2>/dev/null
}
issue index "subjectAltName=DNS:index,DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth,clientAuth
keyUsage=critical,digitalSignature,keyEncipherment"
issue regwatch-index-admin "extendedKeyUsage=clientAuth
keyUsage=critical,digitalSignature,keyEncipherment"
mv index.pem node.pem && mv index-key.pem node-key.pem
mv regwatch-index-admin.pem admin.pem && mv regwatch-index-admin-key.pem admin-key.pem

secret() { od -An -tx1 -N24 /dev/urandom | tr -d ' \n'; }
search_pw="$(secret)"
indexer_pw="$(secret)"
printf 'SEARCH_PW=%s\nINDEXER_PW=%s\n' "$search_pw" "$indexer_pw" > passwords.env

if [[ -d "$out" ]]; then  # the old files belong to the container's user
  docker run --rm --user 0 --network none -v "$out:/out" --entrypoint bash "$image" \
    -c 'rm -rf /out/certs /out/security /out/admin'
fi
rm -rf "$out"
mkdir -p "$out/certs" "$out/security" "$out/admin"
chmod 755 "$out" "$out/certs" "$out/security"
cp ca.pem admin.pem admin-key.pem "$out/admin/"
mkdir -p in && cp ca.pem node.pem node-key.pem in/
chmod 755 in && chmod 644 in/*
# Inside the image: hash the passwords with the plugin's own tool, and leave every generated
# file owned by the container's user (uid 1000) with mode 600 (the host user differs).
docker run --rm --user 0 --network none \
  --env-file "$work/passwords.env" \
  -v "$work/in:/in:ro" -v "$root/deploy/opensearch/security:/committed:ro" -v "$out:/out" \
  --entrypoint bash "$image" -c '
    set -euo pipefail
    hash() {  # an empty or malformed hash stops the setup
      got="$(/usr/share/opensearch/plugins/opensearch-security/tools/hash.sh -env "$1" 2>/dev/null | tail -1)"
      [[ "$got" == \$2* ]] || { echo "hashing $1 failed" >&2; exit 1; }
      echo "$got"
    }
    search_hash="$(hash SEARCH_PW)"
    indexer_hash="$(hash INDEXER_PW)"
    cp /in/ca.pem /in/node.pem /in/node-key.pem /out/certs/
    cp /committed/*.yml /out/security/
    {
      echo "_meta: { type: internalusers, config_version: 2 }"
      echo "regwatch_search:"
      echo "  hash: \"$search_hash\""
      echo "  description: the API, read only (role regwatch_search)"
      echo "regwatch_indexer:"
      echo "  hash: \"$indexer_hash\""
      echo "  description: the worker (role regwatch_indexer)"
    } > /out/security/internal_users.yml
    chown -R 1000:1000 /out/certs /out/security
    chmod 700 /out/certs /out/security
    chmod 600 /out/certs/* /out/security/*'
env_for() {  # service, user, password, file
  {
    echo "# Generated by scripts/index-setup.sh for local development. Never commit."
    echo "# The index sidecar's $2 user (ADR-0011): the $1 service only."
    echo "REGWATCH_INDEX_URL=https://index:9200"
    echo "REGWATCH_INDEX_USER=$2"
    echo "REGWATCH_INDEX_PASSWORD=$3"
    echo "REGWATCH_INDEX_CA_B64=$(base64 -w0 ca.pem)"
  } > "$4"
  chmod 600 "$4"
}
env_for api regwatch_search "$search_pw" "$envfile"
env_for worker regwatch_indexer "$indexer_pw" "$workerfile"
echo "wrote deploy/opensearch/generated/, deploy/index.env and deploy/index-worker.env;"
echo "start it with docker compose --profile index up -d"
