#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

version=$(tr -d '[:space:]' < VERSION)
if [[ ! $version =~ ^[0-9]+[.][0-9]+[.][0-9]+([+~.-][A-Za-z0-9.]+)?$ ]]; then
    printf 'Invalid VERSION value: %q\n' "$version" >&2
    exit 2
fi

for command_name in dpkg-buildpackage dpkg-deb dh; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Missing package build command: %s\n' "$command_name" >&2
        exit 1
    fi
done

package_version=$(dpkg-parsechangelog -S Version)
if [[ $package_version != "$version-1" ]]; then
    printf 'Debian changelog version %s does not match functional version %s-1.\n' \
        "$package_version" "$version" >&2
    exit 1
fi

output_dir=${1:-dist}
mkdir -p -- "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
source_root="$work_dir/bhola-pulse-$version"
mkdir -p -- "$source_root"

tar \
    --exclude=.git \
    --exclude=build \
    --exclude=dist \
    --exclude=debian/bhola-pulse \
    --exclude='*/__pycache__' \
    --exclude='*.py[co]' \
    -cf - . | tar -xf - -C "$source_root"

(
    cd "$source_root"
    dpkg-buildpackage --build=binary --unsigned-source --unsigned-changes
)

deb_name="bhola-pulse_${package_version}_all.deb"
deb_source="$work_dir/$deb_name"
deb_path="$output_dir/$deb_name"
test -f "$deb_source"
install -m 0644 "$deb_source" "$deb_path"
rm -f -- "$output_dir/SHA256SUMS"
(
    cd -- "$output_dir"
    sha256sum "$deb_name" > SHA256SUMS
)

dpkg-deb --info "$deb_path" >/dev/null
dpkg-deb --contents "$deb_path" >/dev/null
printf 'Built %s\n' "$deb_path"
printf 'Checksum: %s\n' "$output_dir/SHA256SUMS"
