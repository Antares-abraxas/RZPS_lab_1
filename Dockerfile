FROM postgres:18

RUN localedef -i ru_RU -c -f UTF-8 -A /usr/share/locale/locale.alias ru_RU.UTF-8
ENV LANG=ru_RU.utf8

COPY --chown=postgres:postgres postgresql.conf /etc/postgresql/postgresql.conf
COPY --chown=postgres:postgres sql/ /opt/sql/
COPY --chmod=755 docker/initdb/ /docker-entrypoint-initdb.d/

CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]