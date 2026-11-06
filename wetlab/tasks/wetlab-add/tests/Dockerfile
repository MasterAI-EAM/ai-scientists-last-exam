FROM python:3.12-slim-bookworm
COPY verify.py test.sh /tests/
RUN chmod 500 /tests/test.sh && mkdir -p /ledger /logs/verifier
WORKDIR /tests
