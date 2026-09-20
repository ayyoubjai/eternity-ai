#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="digital-clone:local"
force_build=0
host_uid="${SUDO_UID:-$(id -u)}"
host_gid="${SUDO_GID:-$(id -g)}"
caller_home="$(getent passwd "${host_uid}" 2>/dev/null | cut -d: -f6)"
caller_home="${caller_home:-${HOME}}"

if [[ "${1:-}" == "--build" ]]; then
    force_build=1
    shift
fi

mkdir -p \
    "${repo_root}/inputs" \
    "${repo_root}/outputs" \
    "${repo_root}/.cache/huggingface" \
    "${repo_root}/.runtime/home" \
    "${repo_root}/vendors/Ditto/checkpoints"

# When the Docker client needs sudo, keep runtime directories writable by the
# desktop user whose display and audio sockets are forwarded to the container.
if [[ "$(id -u)" == "0" && -n "${SUDO_UID:-}" ]]; then
    chown "${host_uid}:${host_gid}" \
        "${repo_root}/outputs" \
        "${repo_root}/.cache/huggingface" \
        "${repo_root}/.runtime/home"
fi

if [[ "${force_build}" == "1" ]] || ! docker image inspect "${image_name}" >/dev/null 2>&1; then
    # Some Linux Docker installations have broken bridge DNS even though the
    # host resolves normally. Builds need network only for apt/pip downloads,
    # so using the host network avoids that daemon DNS mismatch.
    docker build --network host -t "${image_name}" "${repo_root}"
fi

docker_args=(
    --rm
    -it
    --gpus all
    --network host
    --ipc host
    --user "${host_uid}:${host_gid}"
    -e HOME=/home/digital-clone
    -e HF_HOME=/cache/huggingface
    -v "${repo_root}/inputs:/app/inputs:ro"
    -v "${repo_root}/outputs:/app/outputs"
    -v "${repo_root}/vendors/Ditto/checkpoints:/app/vendors/Ditto/checkpoints:ro"
    -v "${repo_root}/.cache/huggingface:/cache/huggingface"
    -v "${repo_root}/.runtime/home:/home/digital-clone"
)

if [[ -n "${DISPLAY:-}" ]]; then
    docker_args+=(
        -e DISPLAY
        -v /tmp/.X11-unix:/tmp/.X11-unix:ro
    )

    xauthority_path="${XAUTHORITY:-${caller_home}/.Xauthority}"
    if [[ -f "${xauthority_path}" ]]; then
        docker_args+=(
            -e XAUTHORITY=/tmp/.Xauthority
            -v "${xauthority_path}:/tmp/.Xauthority:ro"
        )
    fi
else
    requested_args=" $* "
    if [[ "${requested_args}" == *" --mode live "* || "${requested_args}" == *" --mode=live "* ]]; then
        echo "Live mode requires a desktop DISPLAY; use offline --no-playback here." >&2
        exit 1
    fi
    echo "No DISPLAY detected; offline output will be saved without playback." >&2
    set -- --no-playback "$@"
fi

desktop_runtime_dir="${XDG_RUNTIME_DIR:-/run/user/${host_uid}}"
if [[ -d "${desktop_runtime_dir}" ]]; then
    docker_args+=(
        -e "XDG_RUNTIME_DIR=${desktop_runtime_dir}"
        -e "PULSE_SERVER=unix:${desktop_runtime_dir}/pulse/native"
        -v "${desktop_runtime_dir}:${desktop_runtime_dir}"
    )
else
    echo "No desktop audio runtime detected; playback may be silent." >&2
fi

exec docker run "${docker_args[@]}" "${image_name}" "$@"
