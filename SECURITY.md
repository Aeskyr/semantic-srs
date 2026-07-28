# Security

Please report vulnerabilities privately through GitHub Security Advisories for
`Aeskyr/semantic-srs`. Do not include learner databases, source excerpts, tokens,
or model-cache contents in a report. Supported security fixes target the latest
released 0.2.x version.

The dashboard binds only to `127.0.0.1`, uses a fresh bearer token per launch,
and rejects non-local Host and Origin values. Semantic SRS and Local RAG make no
telemetry calls. Network access is used only to install Python dependencies and
download the Local RAG embedding model.
