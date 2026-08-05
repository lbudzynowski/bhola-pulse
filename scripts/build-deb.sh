#!/usr/bin/env bash
set -euo pipefail
umask 0022

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if ! git_root=$(git -C "$project_root" rev-parse --show-toplevel 2>/dev/null); then
    printf 'Package build requires a valid Git worktree.\n' >&2
    exit 1
fi
git_root=$(cd -- "$git_root" && pwd)
if [[ $git_root != "$project_root" ]] || \
   [[ $(git -C "$project_root" rev-parse --is-inside-work-tree 2>/dev/null) != true ]]; then
    printf 'Package build script is not at the root of its Git worktree.\n' >&2
    exit 1
fi

if ! head_commit=$(git -C "$project_root" rev-parse --verify --quiet 'HEAD^{commit}'); then
    printf 'Package build requires a valid committed HEAD.\n' >&2
    exit 1
fi
if ! worktree_state=$(
    git -C "$project_root" status --porcelain=v1 --untracked-files=all 2>&1
); then
    printf 'Unable to verify Git worktree state; refusing package build.\n' >&2
    exit 1
fi
if [[ -n $worktree_state ]]; then
    printf 'Package build requires a clean worktree with no staged, modified, or untracked files.\n' >&2
    exit 1
fi

for command_name in git tar dpkg-buildpackage dpkg-parsechangelog dpkg-deb dh sha256sum install; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Missing package build command: %s\n' "$command_name" >&2
        exit 1
    fi
done

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
if ! git -C "$project_root" -c tar.umask=0022 archive \
    --format=tar \
    --prefix=source/ \
    "$head_commit" | tar --extract --no-same-owner --directory="$work_dir"; then
    printf 'Unable to create committed source snapshot.\n' >&2
    exit 1
fi
source_root="$work_dir/source"

version=$(tr -d '[:space:]' < "$source_root/VERSION")
if [[ ! $version =~ ^[0-9]+[.][0-9]+[.][0-9]+([+~.-][A-Za-z0-9.]+)?$ ]]; then
    printf 'Invalid VERSION value: %q\n' "$version" >&2
    exit 2
fi

package_version=$(dpkg-parsechangelog -l"$source_root/debian/changelog" -S Version)
if [[ $package_version != "$version-1" ]]; then
    printf 'Debian changelog version %s does not match functional version %s-1.\n' \
        "$package_version" "$version" >&2
    exit 1
fi

cd "$project_root"
output_dir=${1:-dist}
mkdir -p -- "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd)

(
    cd "$source_root"
    dpkg-buildpackage --build=binary --unsigned-source --unsigned-changes
)

deb_name="bhola-pulse_${package_version}_all.deb"
deb_source="$work_dir/$deb_name"
deb_path="$output_dir/$deb_name"
test -f "$deb_source"
install -m 0644 "$deb_source" "$deb_path"
checksum_path="$work_dir/SHA256SUMS"
(
    cd -- "$output_dir"
    sha256sum "$deb_name"
) > "$checksum_path"
install -m 0644 "$checksum_path" "$output_dir/SHA256SUMS"

dpkg-deb --info "$deb_path" >/dev/null
dpkg-deb --contents "$deb_path" >/dev/null
printf 'Built %s\n' "$deb_path"
printf 'Checksum: %s\n' "$output_dir/SHA256SUMS"
