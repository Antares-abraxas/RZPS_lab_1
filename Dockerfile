FROM postgres:18

ENV LANG=ru_RU.utf8
RUN localedef -i ru_RU -c -f UTF-8 -A /usr/share/locale/locale.alias ru_RU.UTF-8
COPY --chmod=755 docker/initdb/ /docker-entrypoint-initdb.d/
