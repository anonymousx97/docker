FROM python:3.14-slim-trixie AS builder

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv


RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        zlib1g-dev \
        curl \
        xz-utils


RUN case $(uname -m) in \
        x86_64) TARGET="linux64" ;; \
        aarch64|arm64) TARGET="linuxarm64" ;; \
        *) echo "Unsupported architecture" && exit 1 ;; \
    esac && \
    curl -sL "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-${TARGET}-gpl.tar.xz" \
        | tar -xJ --strip-components=2 -C /usr/local/bin --wildcards '*/bin/ffmpeg' '*/bin/ffprobe'


COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --seed /opt/venv && \
      uv pip install --upgrade pip setuptools wheel && \
      uv pip install -r requirements.txt && \
    # Strip Debug things from libs
    find /opt/venv -type d \( -name "tests" -o -name "test" -o -name "idlelib" \) -prune -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.so" -exec strip --strip-unneeded {} + 2>/dev/null || true



### Actual Image


FROM python:3.14-slim-trixie

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1


RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    # basic packages
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl git nano wget unzip fastfetch tar xz-utils && \
    # cleanup
    rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/locale/* /usr/share/info/* && \
    # git defaults
    git config --global user.email "88324835+anonymousx97@users.noreply.github" && \
    git config --global user.name "anonymousx97"


COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=builder /bin/uv /bin/uv
COPY --from=builder /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=builder /usr/local/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=builder /opt/venv /opt/venv


EXPOSE 8080 22 8022
 
COPY start .
CMD [ "./start" ]
