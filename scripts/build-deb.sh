#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

version=$(tr -d '[:space:]' < VERSION)
if [[ ! $version =~ ^[0-9]+[.][0-9]+[.][0-9]+([+~.-][A-Za-z0-9.]+)?$ ]]; then
    printf 'Invalid VERSION value: %q\n' "$version" >&2
    exit 2
fi

output_dir=${1:-dist}
mkdir -p -- "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

package_root="$work_dir/bhola-pulse_${version}_all"
deb_path="$output_dir/bhola-pulse_${version}_all.deb"

install -d \
    "$package_root/DEBIAN" \
    "$package_root/usr/bin" \
    "$package_root/usr/lib/bhola-pulse" \
    "$package_root/usr/lib/bhola-pulse/scripts" \
    "$package_root/usr/share/doc/bhola-pulse"

sed "s/@VERSION@/$version/g" packaging/debian/control.in > "$package_root/DEBIAN/control"
install -m 0755 packaging/bhola-pulse "$package_root/usr/bin/bhola-pulse"
install -m 0755 scripts/run-dev.sh "$package_root/usr/lib/bhola-pulse/scripts/run-dev.sh"
install -m 0644 VERSION "$package_root/usr/lib/bhola-pulse/VERSION"
install -m 0644 README.md "$package_root/usr/share/doc/bhola-pulse/README.md"
install -m 0644 packaging/debian/copyright "$package_root/usr/share/doc/bhola-pulse/copyright"

cp -a src conky config "$package_root/usr/lib/bhola-pulse/"
find "$package_root/usr/lib/bhola-pulse" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$package_root/usr/lib/bhola-pulse" -type f -name '*.py[co]' -delete
find "$package_root" -type d -exec chmod 0755 {} +
find "$package_root/usr/lib/bhola-pulse" -type f -exec chmod 0644 {} +
chmod 0755 "$package_root/usr/lib/bhola-pulse/scripts/run-dev.sh"

mapfile -d '' unexpected_directories < <(
    find "$package_root" -type d ! -perm 0755 -print0
)
if (( ${#unexpected_directories[@]} > 0 )); then
    printf 'Refusing to build package: directories with modes other than 0755:\n' >&2
    for directory in "${unexpected_directories[@]}"; do
        printf '  .%s (mode %s)\n' \
            "${directory#"$package_root"}" \
            "$(stat -c '%a' -- "$directory")" >&2
    done
    exit 1
fi

rm -f -- "$deb_path" "$output_dir/SHA256SUMS"
dpkg-deb --root-owner-group --build "$package_root" "$deb_path"
(
    cd -- "$output_dir"
    sha256sum "$(basename -- "$deb_path")" > SHA256SUMS
)

dpkg-deb --info "$deb_path" >/dev/null
dpkg-deb --contents "$deb_path" >/dev/null
printf 'Built %s\n' "$deb_path"
printf 'Checksum: %s\n' "$output_dir/SHA256SUMS"
