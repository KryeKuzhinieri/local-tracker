#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_id="io.github.localtracker.LocalTracker"
install_root="${XDG_DATA_HOME:-$HOME/.local/share}/local-tracker/app"
bin_dir="$HOME/.local/bin"
applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

if ! /usr/bin/python3 -c \
  "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')" \
  >/dev/null 2>&1; then
  echo "Missing GTK Python bindings." >&2
  echo "Install: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" >&2
  exit 1
fi

mkdir -p "$install_root" "$bin_dir" "$applications_dir" "$icons_dir"
rm -rf "$install_root/local_tracker"
cp -R "$project_root/local_tracker" "$install_root/local_tracker"

cat >"$bin_dir/local-tracker" <<EOF
#!/usr/bin/env sh
export PYTHONPATH="$install_root"
exec /usr/bin/python3 -m local_tracker "\$@"
EOF
chmod 755 "$bin_dir/local-tracker"

sed "s|^Exec=.*|Exec=$bin_dir/local-tracker|" \
  "$project_root/data/$app_id.desktop" >"$applications_dir/$app_id.desktop"
chmod 644 "$applications_dir/$app_id.desktop"
install -m 644 "$project_root/data/$app_id.svg" "$icons_dir/$app_id.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$applications_dir"
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" \
    >/dev/null 2>&1 || true
fi

echo "Local Tracker is installed for this user."
echo "Search for “Local Tracker” in Ubuntu's application overview."
