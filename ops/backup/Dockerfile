FROM postgres:16-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends awscli ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY backup_database.sh restore_drill.sh /usr/local/bin/
RUN chmod 0555 /usr/local/bin/backup_database.sh /usr/local/bin/restore_drill.sh \
    && useradd --system --uid 10001 --gid operator backupoperator
USER 10001
ENTRYPOINT ["/usr/local/bin/backup_database.sh"]
