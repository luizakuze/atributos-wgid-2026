FROM osixia/openldap:1.5.0

COPY bootstrap/01-bob.ldif /container/service/slapd/assets/config/bootstrap/ldif/custom/01-bob.ldif

RUN chown -R 911:911 /container/service/slapd/assets/config/bootstrap/ldif/custom
