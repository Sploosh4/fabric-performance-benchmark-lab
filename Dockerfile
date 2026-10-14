FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/fabric-lab
COPY scripts/ scripts/
COPY scenarios/ scenarios/
COPY presets/ presets/
COPY manifests/ manifests/
COPY bootstrap-helper/src/ bootstrap-helper/src/
COPY bootstrap-helper/resources/ bootstrap-helper/resources/
COPY bootstrap-helper/tests/ bootstrap-helper/tests/
COPY LICENSE THIRD_PARTY_NOTICES.md ./
RUN groupadd --gid 10001 lab && useradd --uid 10001 --gid lab --no-create-home lab \
    && mkdir -p /data/input /data/output
USER 10001:10001
ENTRYPOINT ["python", "scripts/offline.py"]
CMD ["--help"]
