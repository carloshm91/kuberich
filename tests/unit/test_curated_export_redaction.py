"""Trust bytes stay concealed in default webhook exports at any nesting depth."""

from kuberich.domain.exports import ResourceSource, read_artifact
from kuberich.domain.resources import resource_record
from tests.support.curated_policy import CA_CANARY, policy_manifest, policy_resource
from tests.unit.test_exports import ID, prepared


def test_default_export_conceals_webhook_ca_bytes_and_preserves_service_reference():
    resource = policy_resource("mutatingwebhookconfigurations")
    body = policy_manifest(resource.name)
    body["webhooks"][0]["clientConfig"]["caBundle"] = CA_CANARY
    source = ResourceSource(resource=resource, record=resource_record(resource, body))
    result = prepared(source, "resource-yaml")
    assert CA_CANARY.encode() not in result.payload
    assert "caBundle: '[REDACTED]'" in result.payload.decode()
    assert "service:" in result.payload.decode()
    assert read_artifact(result.payload, artifact_id=ID).payload == result.payload
