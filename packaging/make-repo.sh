#!/bin/sh
# Assemble the published zypper repository under ./public/ from ./dist/*.rpm.
#
# Environment:
#   PAGES_OWNER, PAGES_REPO   GitHub owner / repo name -> used for the baseurl
#   GPG_PRIVATE_KEY           ASCII-armored *passphrase-less* private key.
#                             If set, the RPMs and the repo metadata are signed
#                             and the generated .repo turns gpg checking on.
#
# Called by .github/workflows/release.yml. Needs: createrepo_c, rpm, gpg.

set -eu

OWNER=$(printf '%s' "${PAGES_OWNER:?PAGES_OWNER not set}" | tr '[:upper:]' '[:lower:]')
REPO="${PAGES_REPO:?PAGES_REPO not set}"
BASE="https://$OWNER.github.io/$REPO"

rm -rf public
mkdir public
cp dist/*.rpm public/

if [ -n "${GPG_PRIVATE_KEY:-}" ]; then
    GNUPGHOME=$(mktemp -d)
    export GNUPGHOME
    chmod 700 "$GNUPGHOME"
    printf 'pinentry-mode loopback\nno-tty\n' > "$GNUPGHOME/gpg.conf"
    printf '%s\n' "$GPG_PRIVATE_KEY" | gpg --batch --import
    FPR=$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr:/{print $10; exit}')
    echo "Signing with key $FPR"

    # --- sign each RPM package (gpgcheck / pkg_gpgcheck) ---
    cat > "$HOME/.rpmmacros" <<RPMMACROS
%_gpg_name $FPR
%__gpg_sign_cmd %{__gpg} gpg --batch --pinentry-mode loopback --no-armor --no-tty -u "%{_gpg_name}" -sbo %{__signature_filename} --digest-algo sha256 %{__plaintext_filename}
RPMMACROS
    for r in public/*.rpm; do
        rpm --addsign "$r"
    done
    # Show the signature that landed in each header (needs no keyring).
    rpm -qp --qf '%{name}-%{version}: %{RSAHEADER:pgpsig}\n' public/*.rpm

    # --- sign the repo metadata (repo_gpgcheck) + publish the public key ---
    gpg --batch --armor --export "$FPR" > public/tumbleweed-updater.key
    createrepo_c public/
    gpg --batch --yes --detach-sign --armor public/repodata/repomd.xml

    GPG_BLOCK="gpgcheck=1
repo_gpgcheck=1
pkg_gpgcheck=1
gpgkey=$BASE/tumbleweed-updater.key"
else
    createrepo_c public/
    GPG_BLOCK="gpgcheck=0
repo_gpgcheck=0"
fi

cat > public/tumbleweed-updater.repo <<REPO
[tumbleweed-updater]
name=Tumbleweed Updater
baseurl=$BASE
enabled=1
autorefresh=1
type=rpm-md
$GPG_BLOCK
REPO

echo "--- public/ ---"
find public -type f | sort
echo "--- tumbleweed-updater.repo ---"
cat public/tumbleweed-updater.repo
