FROM python:3.12-slim-bookworm
RUN apt-get -o Acquire::Retries=8 update && apt-get -o Acquire::Retries=8 install -y --no-install-recommends \
        bash ca-certificates curl git nodejs npm ripgrep procps \
    && rm -rf /var/lib/apt/lists/*
COPY wetlab /usr/local/bin/wetlab
COPY wetlab /usr/local/bin/wait_for_result
RUN chmod 555 /usr/local/bin/wetlab /usr/local/bin/wait_for_result && mkdir -p /app
WORKDIR /app
CMD ["sleep", "infinity"]
