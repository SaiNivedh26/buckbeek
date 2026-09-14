#!/bin/sh
set -eu

install_dir="${HOME}/.local/bin"
mkdir -p "${install_dir}"
cp "$(dirname "$0")/tool" "${install_dir}/tool"
chmod 0755 "${install_dir}/tool"
echo "Installed tool to ${install_dir}/tool"
case ":${PATH}:" in
  *":${install_dir}:"*) ;;
  *) echo "Add ${install_dir} to PATH to run it as 'tool'." ;;
esac
